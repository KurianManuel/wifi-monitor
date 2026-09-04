"""
Jio Router Logout and Session Cleanup Interface.

Phase 1 / Interface Only:
Real Jio logout behavior will be integrated strictly after the working
implementation is analyzed in Phase 7.
DO NOT GUESS OR INVENT JIO LOGOUT PROTOCOLS HERE.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from login import JioSession

logger = logging.getLogger("jio_wifi_tracker.logout")


class JioLogoutInterface(ABC):
    """Abstract interface for terminating router sessions safely."""

    @abstractmethod
    def logout(self, session: Optional[JioSession]) -> bool:
        """Terminate the router session on the physical router."""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up local session caches/tokens."""
        pass


class PlaceholderJioLogout(JioLogoutInterface):
    """
    Placeholder logout handler for Phase 1 and Mock Mode.
    """

    def __init__(self, host: str):
        self.host = host

    def logout(self, session: Optional[JioSession]) -> bool:
        logger.info("Placeholder logout called for host: %s (Mode: Placeholder/Mock)", self.host)
        if session:
            session.authenticated = False
        return True

    def cleanup(self) -> None:
        logger.info("Placeholder session cleanup executed.")
