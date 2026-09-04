"""
Unit tests for placeholder authentication, logout, and collector interfaces.
Verifies contract adherence and counter delta calculation logic.
"""

import pytest
from collector import DataCollector, calculate_delta
from login import JioAuthInterface, JioSession, PlaceholderJioAuth
from logout import JioLogoutInterface, PlaceholderJioLogout


def test_placeholder_auth_interface():
    """Verify login interface contract."""
    auth = PlaceholderJioAuth("192.168.29.1", "admin")
    assert isinstance(auth, JioAuthInterface)
    assert not auth.is_authenticated()

    session = auth.login()
    assert session is not None
    assert session.is_valid()
    assert auth.is_authenticated()

    auth.invalidate_session()
    assert not auth.is_authenticated()


def test_placeholder_logout_interface():
    """Verify logout interface contract."""
    logout_handler = PlaceholderJioLogout("192.168.29.1")
    assert isinstance(logout_handler, JioLogoutInterface)
    
    session = JioSession(session_id="test-session-123", authenticated=True)
    assert session.is_valid()

    res = logout_handler.logout(session)
    assert res is True
    assert not session.is_valid()

    # Cleanup executes without error
    logout_handler.cleanup()


def test_calculate_delta_logic():
    """
    Test counter delta rules:
    - Normal increase: curr - prev
    - Counter reset: curr < prev -> 0 (no negative traffic, no spike)
    - Initial sample: prev is None -> 0
    """
    # Initial sample
    assert calculate_delta(1000, None) == 0

    # Normal increase
    assert calculate_delta(1500, 1000) == 500

    # Zero change
    assert calculate_delta(1500, 1500) == 0

    # Counter reset (e.g. router reboot)
    assert calculate_delta(200, 1500) == 0


def test_collector_session_handling():
    """Test collector session verification."""
    collector = DataCollector()
    assert collector.ensure_session() is True
    assert collector.session is not None
    assert collector.session.is_valid()
