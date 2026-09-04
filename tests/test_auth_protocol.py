"""
Unit tests for Jio Router Protocol Driver, Authentication, and Logout.

Uses requests mocking to verify:
- Exact JSON-RPC payloads
- Headers (Origin, Referer, Authorization, Cookie)
- Dual credential handling (Bearer + sysauth)
- Normal login and duplicate admin login flows
- Session confirmation and expiration handling
- Clean logout confirmation
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest
import requests

from login import JioRouterAuth, JioSession, PlaceholderJioAuth
from logout import JioRouterLogout, PlaceholderJioLogout
from router_api import JioRouterClient, JioRouterError, SessionExpiredError


# ------------------------------------------------------------------------------
# 1. router_api.py Tests
# ------------------------------------------------------------------------------

def test_router_client_pre_login_success():
    """Verify preLogin request structure and response verification."""
    client = JioRouterClient("192.168.29.1")
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "OK", "id": "test-id"}

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        res = client.pre_login()
        assert res["status"] == "OK"
        
        args, kwargs = mock_post.call_args
        assert args[0] == "https://192.168.29.1/WCGI"
        assert kwargs["json"]["method"] == "preLogin"
        assert kwargs["headers"]["Origin"] == "https://192.168.29.1"
        assert kwargs["headers"]["Referer"] == "https://192.168.29.1/"


def test_router_client_normal_login():
    """Verify login parsing with token split format 'BEARER-SYSAUTH'."""
    client = JioRouterClient("192.168.29.1", "admin", "secret")
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "OK",
        "results": {
            "token": "bearer12345-sysauth67890",
            "loggedId": None
        }
    }

    with patch.object(client.session, "post", return_value=mock_resp):
        res = client.login()
        assert res["status"] == "OK"
        assert client.bearer == "bearer12345"
        assert client.sysauth == "sysauth67890"


def test_router_client_duplicate_admin_login():
    """Verify duplicate admin login response handling (loggedId & bearer)."""
    client = JioRouterClient("192.168.29.1", "admin", "secret")
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": "ERR_LOGIN_DUPLICATE_ADMIN",
        "results": {
            "token": "bearer999",
            "loggedId": "admin-session-xyz"
        }
    }
    # Set sysauth cookie on the session
    client.session.cookies.set("sysauth", "cookie_sysauth_val", domain="192.168.29.1", path="/")

    with patch.object(client.session, "post", return_value=mock_resp):
        res = client.login()

        assert res["code"] == "ERR_LOGIN_DUPLICATE_ADMIN"
        assert client.bearer == "bearer999"
        assert client.logged_id == "admin-session-xyz"
        assert client.sysauth == "cookie_sysauth_val"


def test_router_client_post_login():
    """Verify postLogin payload contains authHeader and loggedId."""
    client = JioRouterClient("192.168.29.1")
    client.bearer = "bearer123"
    client.logged_id = "session_xyz"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "OK"}

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        res = client.post_login()
        assert res["status"] == "OK"
        
        kwargs = mock_post.call_args[1]
        assert kwargs["json"]["method"] == "postLogin"
        assert kwargs["json"]["params"]["authHeader"] == "Bearer bearer123"
        assert kwargs["json"]["params"]["loggedId"] == "session_xyz"


def test_router_client_session_expired_detection_401():
    """Verify HTTP 401 triggers SessionExpiredError."""
    client = JioRouterClient("192.168.29.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch.object(client.session, "post", return_value=mock_resp):
        with pytest.raises(SessionExpiredError):
            client.get_session_status()


def test_router_client_session_expired_detection_code():
    """Verify ERR_UNAUTHORIZED_OR_EXPIRED triggers SessionExpiredError."""
    client = JioRouterClient("192.168.29.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"code": "ERR_UNAUTHORIZED_OR_EXPIRED"}

    with patch.object(client.session, "post", return_value=mock_resp):
        with pytest.raises(SessionExpiredError):
            client.get_session_status()


def test_router_client_get_clients_merge():
    """Verify wireless and LAN device merging on normalized MAC address."""
    client = JioRouterClient("192.168.29.1")
    client.bearer = "token"
    client.sysauth = "auth"

    mock_wireless = [
        {
            "macAddress": "AA:BB:CC:11:22:33",
            "radio": "5GHz",
            "ssid": "JioFiber-5G",
            "bytesRx": 500,
            "bytesTx": 1000
        }
    ]
    mock_lan = [
        {
            "macAddress": "aa:bb:cc:11:22:33",
            "ipv4Address": "192.168.29.45",
            "hostName": "User-Laptop"
        }
    ]

    with patch.object(client, "get_wireless_clients", return_value=mock_wireless), \
         patch.object(client, "get_lan_clients", return_value=mock_lan):
        clients = client.get_clients()
        assert len(clients) == 1
        dev = clients[0]
        assert dev["macAddress"] == "aa:bb:cc:11:22:33"
        assert dev["hostName"] == "User-Laptop"
        assert dev["ipv4Address"] == "192.168.29.45"
        assert dev["bytesRx"] == 500
        assert dev["bytesTx"] == 1000


# ------------------------------------------------------------------------------
# 2. login.py & Session Lifecycle Tests
# ------------------------------------------------------------------------------

def test_jio_session_save_and_load():
    """Verify session serialization and loading."""
    fd, session_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)

    try:
        session = JioSession("b123", "s456", "192.168.29.1", "admin", "log999")
        session.save(session_file)

        loaded = JioSession.load(session_file)
        assert loaded is not None
        assert loaded.bearer == "b123"
        assert loaded.sysauth == "s456"
        assert loaded.router_host == "192.168.29.1"
        assert loaded.logged_id == "log999"
        assert loaded.is_valid()
    finally:
        if os.path.exists(session_file):
            os.remove(session_file)


def test_jio_router_auth_login_sequence():
    """Verify full JioRouterAuth login sequence."""
    fd, session_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)

    auth = JioRouterAuth("192.168.29.1", "admin", "test_password", session_file=session_file)

    with patch.object(auth.client, "pre_login") as mock_pre, \
         patch.object(auth.client, "login") as mock_login, \
         patch.object(auth.client, "post_login") as mock_post, \
         patch.object(auth.client, "get_session_status") as mock_status:
        
        # Simulate successful login setting tokens
        def fake_login(*args, **kwargs):
            auth.client.bearer = "bearer_val"
            auth.client.sysauth = "sysauth_val"
            return {"status": "OK"}
        
        mock_login.side_effect = fake_login

        session = auth.login(force_refresh=True)
        assert session is not None
        assert session.bearer == "bearer_val"
        assert session.sysauth == "sysauth_val"

        mock_pre.assert_called_once()
        mock_login.assert_called_once()
        mock_post.assert_called_once()
        mock_status.assert_called_once()

    if os.path.exists(session_file):
        os.remove(session_file)


# ------------------------------------------------------------------------------
# 3. logout.py Tests
# ------------------------------------------------------------------------------

def test_jio_router_logout_success():
    """Verify logout removes session file only on confirmed OK_LOGOUT."""
    fd, session_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)

    session = JioSession("bearer_1", "sysauth_1", "192.168.29.1")
    session.save(session_file)
    assert os.path.exists(session_file)

    logout_handler = JioRouterLogout("192.168.29.1", session_file=session_file)
    
    with patch.object(logout_handler.client, "logout", return_value={"status": "OK", "code": "OK_LOGOUT"}):
        success = logout_handler.logout(session)
        assert success is True
        assert not os.path.exists(session_file)
        assert not session.is_valid()


def test_jio_router_logout_unconfirmed_retains_session():
    """Verify logout retains session file if router does not return OK_LOGOUT."""
    fd, session_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)

    try:
        session = JioSession("bearer_1", "sysauth_1", "192.168.29.1")
        session.save(session_file)

        logout_handler = JioRouterLogout("192.168.29.1", session_file=session_file)
        
        with patch.object(logout_handler.client, "logout", return_value={"status": "ERR", "code": "FAILED"}):
            success = logout_handler.logout(session)
            assert success is False
            # Session file must be preserved
            assert os.path.exists(session_file)
    finally:
        if os.path.exists(session_file):
            os.remove(session_file)
