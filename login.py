"""
Jio Router Authentication Interface and Placeholders.

Phase 1 / Interface Only:
Real Jio authentication will be implemented strictly after analysis of
the existing working implementation in Phase 5 & 6.
DO NOT GUESS OR INVENT JIO AUTHENTICATION PROTOCOLS HERE.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger("jio_wifi_tracker.login")


class JioSession:
    """Represents an active router session without exposing credentials."""
    def __init__(self, session_id: str, authenticated: bool = True, expires_at: Optional[float] = None):
        self.session_id = session_id
        self.authenticated = authenticated
        self.expires_at = expires_at

    def is_valid(self) -> bool:
        return self.authenticated


class JioAuthInterface(ABC):
    """Abstract interface defining the contract for Jio router authentication."""

    @abstractmethod
    def login(self) -> Optional[JioSession]:
        """Authenticate with the router and establish a session."""
        pass

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Check if current session is active and valid."""
        pass

    @abstractmethod
    def invalidate_session(self) -> None:
        """Invalidate the local session state."""
        pass


class PlaceholderJioAuth(JioAuthInterface):
    """
    Placeholder authentication handler for Phase 1 and Mock Mode.
    Guarantees no real credentials or guessed endpoints are called.
    """

    def __init__(self, host: str, username: str):
        self.host = host
        self.username = username
        self._current_session: Optional[JioSession] = None

    def login(self) -> Optional[JioSession]:
        logger.info("Placeholder login called for host: %s, user: %s (Mode: Placeholder/Mock)", self.host, self.username)
        self._current_session = JioSession(session_id="mock-session-001", authenticated=True)
        return self._current_session

    def is_authenticated(self) -> bool:
        return self._current_session is not None and self._current_session.is_valid()

    def invalidate_session(self) -> None:
        logger.info("Placeholder session invalidated.")
        self._current_session = None
