"""
Jio Router Logout & Session Termination.

Implements the verified JioFiber/JioAirFiber session cleanup:
1. Calls router JSON-RPC "logout" with authHeader and sysauth cookie
2. Verifies router response: status == "OK" and code == "OK_LOGOUT"
3. Invalidates local session file upon router confirmation
"""

import argparse
import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from config import config
from login import JioSession
from router_api import JioRouterClient

logger = logging.getLogger("jio_wifi_tracker.logout")


class JioLogoutInterface(ABC):
    """Abstract interface for terminating router sessions safely."""

    @abstractmethod
    def logout(self, session: Optional[JioSession] = None) -> bool:
        """Terminate the router session on the physical router."""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up local session caches/tokens."""
        pass


class JioRouterLogout(JioLogoutInterface):
    """
    Production logout handler executing the verified router protocol.
    """

    def __init__(self, router_host: Optional[str] = None, session_file: str = "router_session.json"):
        self.router_host = router_host or config.ROUTER_HOST
        self.session_file = session_file
        self.client = JioRouterClient(self.router_host)

    def logout(self, session: Optional[JioSession] = None) -> bool:
        """
        Execute clean router logout.
        Only removes local credentials after the router confirms logout.
        """
        active_session = session or JioSession.load(self.session_file)
        if not active_session or not active_session.is_valid():
            logger.info("No active session found to log out.")
            self.cleanup()
            return True

        self.client.bearer = active_session.bearer
        self.client.sysauth = active_session.sysauth
        self.client._set_sysauth_cookie()

        try:
            res = self.client.logout()
            if res.get("status") == "OK" and res.get("code") == "OK_LOGOUT":
                logger.info("Router confirmed clean logout. Removing local session file...")
                self.cleanup()
                if session:
                    session.invalidate()
                return True
            else:
                logger.warning("Router logout was not confirmed (response: %s). Session retained.", res)
                return False
        except Exception as e:
            logger.error("Error during router logout: %s", e, exc_info=True)
            return False

    def cleanup(self) -> None:
        """Remove local session file."""
        target = Path(self.session_file)
        if target.is_file():
            try:
                target.unlink()
                logger.info("Saved session file removed: %s", self.session_file)
            except OSError as e:
                logger.warning("Failed to remove session file %s: %s", self.session_file, e)


class PlaceholderJioLogout(JioLogoutInterface):
    """Placeholder logout handler for mock mode and testing."""

    def __init__(self, host: str = "192.168.29.1"):
        self.host = host

    def logout(self, session: Optional[JioSession] = None) -> bool:
        logger.info("Placeholder logout called for host: %s (Mode: Placeholder/Mock)", self.host)
        if session:
            session.invalidate()
        return True

    def cleanup(self) -> None:
        logger.info("Placeholder session cleanup executed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jio Router Logout CLI")
    parser.add_argument("--host", default=config.ROUTER_HOST, help="Router gateway IP")
    parser.add_argument("--session-file", default="router_session.json", help="Path to session file")
    args = parser.parse_args()

    handler = JioRouterLogout(router_host=args.host, session_file=args.session_file)
    success = handler.logout()
    if success:
        print("Logout completed successfully.")
    else:
        print("Logout failed or was not confirmed by router.")
