"""
Jio Router Authentication & Session Management.

Implements the verified JioFiber/JioAirFiber authentication lifecycle:
1. preLogin
2. login (credential submission)
3. postLogin (session binding / force duplicate admin override)
4. getSessionStatus (session confirmation)

Supports persistent session caching, permission hardening (0o600),
and transparent re-authentication on session expiration.
"""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

from config import config
from router_api import JioRouterClient, JioRouterError, SessionExpiredError

logger = logging.getLogger("jio_wifi_tracker.login")


class JioSession:
    """Represents an active, authenticated router session."""

    def __init__(
        self,
        bearer: str,
        sysauth: str,
        router_host: str,
        username: str = "admin",
        logged_id: Optional[str] = None,
        created_at: Optional[float] = None
    ):
        self.bearer = bearer
        self.sysauth = sysauth
        self.router_host = router_host
        self.username = username
        self.logged_id = logged_id
        self.created_at = created_at or time.time()
        self._valid = True

    def is_valid(self) -> bool:
        """Check if session credentials are structurally present and active."""
        return self._valid and bool(self.bearer) and bool(self.sysauth)

    def invalidate(self) -> None:
        """Mark session as invalid."""
        self._valid = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session state for persistence."""
        return {
            "router_ip": self.router_host,
            "username": self.username,
            "bearer": self.bearer,
            "sysauth": self.sysauth,
            "logged_id": self.logged_id,
            "created_at": self.created_at
        }

    def save(self, file_path: str = "router_session.json") -> None:
        """Save session to disk with restrictive 0o600 permissions."""
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

        # Linux user-only read/write
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        logger.debug("Session state securely written to %s", file_path)

    @classmethod
    def load(cls, file_path: str = "router_session.json") -> Optional["JioSession"]:
        """Load saved session from disk if present and valid."""
        target = Path(file_path)
        if not target.is_file():
            return None
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data.get("bearer") or not data.get("sysauth"):
                return None
            return cls(
                bearer=data["bearer"],
                sysauth=data["sysauth"],
                router_host=data.get("router_ip", "192.168.29.1"),
                username=data.get("username", "admin"),
                logged_id=data.get("logged_id"),
                created_at=data.get("created_at")
            )
        except Exception as e:
            logger.warning("Could not load session file %s: %s", file_path, e)
            return None


class JioAuthInterface(ABC):
    """Abstract interface defining the contract for Jio router authentication."""

    @abstractmethod
    def login(self, force_refresh: bool = False) -> Optional[JioSession]:
        """Establish or refresh an authenticated session."""
        pass

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Check if current session is active and valid."""
        pass

    @abstractmethod
    def get_session(self) -> Optional[JioSession]:
        """Return the current active session object."""
        pass

    @abstractmethod
    def invalidate_session(self) -> None:
        """Invalidate the local session state."""
        pass


class JioRouterAuth(JioAuthInterface):
    """
    Production authentication handler executing verified Jio router protocol.
    Reuses cached sessions when valid; automatically re-authenticates when expired.
    """

    def __init__(
        self,
        router_host: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        session_file: str = "router_session.json"
    ):
        self.router_host = router_host or config.ROUTER_HOST
        self.username = username or config.ROUTER_USERNAME
        self.password = password or config.ROUTER_PASSWORD
        self.session_file = session_file
        self.client = JioRouterClient(self.router_host, self.username, self.password)
        self._current_session: Optional[JioSession] = None

    def login(self, force_refresh: bool = False) -> Optional[JioSession]:
        """
        Execute full authentication flow or reuse valid cached session.
        Flow:
          1. Try cached session (if not force_refresh)
          2. preLogin()
          3. login()
          4. postLogin() (with loggedId if duplicate admin)
          5. getSessionStatus()
          6. Persist session
        """
        # 1. Check existing cached session
        if not force_refresh:
            cached = self._current_session or JioSession.load(self.session_file)
            if cached and cached.is_valid():
                # Verify session against live router
                self.client.bearer = cached.bearer
                self.client.sysauth = cached.sysauth
                self.client.logged_id = cached.logged_id
                self.client._set_sysauth_cookie()
                try:
                    self.client.get_session_status()
                    self._current_session = cached
                    logger.info("Existing router session verified and reused.")
                    return self._current_session
                except SessionExpiredError:
                    logger.info("Cached session expired on router. Acquiring fresh session...")
                except Exception as e:
                    logger.warning("Session status check failed: %s. Re-authenticating...", e)

        # 2. Fresh authentication handshake
        if not self.password:
            logger.error("Authentication aborted: No router password configured.")
            return None

        try:
            # Step 1: preLogin
            self.client.pre_login()

            # Step 2: login
            self.client.login(self.username, self.password)

            # Step 3: postLogin (handles normal login and duplicate admin force login)
            self.client.post_login()

            # Step 4: verify
            self.client.get_session_status()

            # Step 5: assemble and save session
            session = JioSession(
                bearer=self.client.bearer,
                sysauth=self.client.sysauth,
                router_host=self.router_host,
                username=self.username,
                logged_id=self.client.logged_id
            )
            session.save(self.session_file)
            self._current_session = session
            logger.info("Jio router authentication successful. New session established.")
            return session

        except Exception as e:
            logger.error("Jio router authentication failed: %s", e, exc_info=True)
            self.invalidate_session()
            return None

    def is_authenticated(self) -> bool:
        return self._current_session is not None and self._current_session.is_valid()

    def get_session(self) -> Optional[JioSession]:
        return self._current_session

    def invalidate_session(self) -> None:
        """Invalidate in-memory and on-disk session state."""
        if self._current_session:
            self._current_session.invalidate()
            self._current_session = None
        self.client.bearer = None
        self.client.sysauth = None
        self.client.logged_id = None
        target = Path(self.session_file)
        if target.is_file():
            try:
                target.unlink()
            except OSError:
                pass


class PlaceholderJioAuth(JioAuthInterface):
    """
    Placeholder authentication handler for Phase 1 and Mock Mode.
    Guarantees no real credentials or physical network endpoints are called.
    """

    def __init__(self, host: str = "192.168.29.1", username: str = "admin"):
        self.host = host
        self.username = username
        self._current_session: Optional[JioSession] = None

    def login(self, force_refresh: bool = False) -> Optional[JioSession]:
        logger.info("Placeholder login called for host: %s, user: %s (Mode: Placeholder/Mock)", self.host, self.username)
        self._current_session = JioSession(
            bearer="mock-bearer-token-1234567890abcdef",
            sysauth="mock-sysauth-token-1234567890abcdef",
            router_host=self.host,
            username=self.username
        )
        return self._current_session

    def is_authenticated(self) -> bool:
        return self._current_session is not None and self._current_session.is_valid()

    def get_session(self) -> Optional[JioSession]:
        return self._current_session

    def invalidate_session(self) -> None:
        logger.info("Placeholder session invalidated.")
        self._current_session = None
