"""
Jio Router Protocol Driver (JioFiber & JioAirFiber).

Low-level JSON-RPC 2.0 transport communicating with Jio gateway firmware at
https://{router_ip}/WCGI.

Preserves the exact verified protocol:
- Methods: preLogin, login, postLogin, getSessionStatus, logout,
           getWirelessClients, getLanClients
- Headers: Content-Type, Origin, Referer, Authorization (Bearer), Cookie (cSupport, sysauth)
- Dual-credential session: Bearer token + sysauth cookie
- Duplicate admin session handling via loggedId override
- Session expiration error detection (HTTP 401 or ERR_UNAUTHORIZED_OR_EXPIRED)
"""

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3

# Suppress InsecureRequestWarning for self-signed router SSL certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("jio_wifi_tracker.router_api")


class SessionExpiredError(Exception):
    """Raised when the router session has expired, is invalid, or rejected."""
    pass


class JioRouterError(Exception):
    """Raised on non-session router API errors."""
    pass


class JioRouterClient:
    """
    Direct client for JioFiber / JioAirFiber gateway firmware.
    Communicates via JSON-RPC 2.0 over HTTPS to /WCGI.
    """

    def __init__(self, router_ip: str, username: str = "admin", password: Optional[str] = None):
        self.router_ip = router_ip
        self.base_url = f"https://{router_ip}/WCGI"
        self.username = username
        self.password = password

        self.session = requests.Session()
        self.session.verify = False

        self.bearer: Optional[str] = None
        self.sysauth: Optional[str] = None
        self.logged_id: Optional[str] = None

    # ==========================================================================
    # JSON-RPC Transport
    # ==========================================================================

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: int = 10) -> Dict[str, Any]:
        """
        Execute a JSON-RPC 2.0 POST request against the router.
        Preserves verified headers, cookies, and error detection.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": str(uuid.uuid4())
        }

        headers = {
            "Content-Type": "application/json",
            "Origin": f"https://{self.router_ip}",
            "Referer": f"https://{self.router_ip}/"
        }

        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"

        if self.sysauth:
            headers["Cookie"] = f"cSupport=1; sysauth={self.sysauth}"

        try:
            response = self.session.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=timeout
            )
        except requests.exceptions.RequestException as e:
            logger.error("Network error while communicating with router at %s: %s", self.base_url, e)
            raise

        if response.status_code == 401:
            logger.warning("Router returned HTTP 401 for method: %s", method)
            raise SessionExpiredError(f"HTTP 401 while calling {method}")

        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as e:
            logger.error("Malformed JSON received from router for method %s: %s", method, e)
            raise JioRouterError(f"Malformed JSON from router: {e}")

        if data.get("code") == "ERR_UNAUTHORIZED_OR_EXPIRED":
            logger.warning("Router reported ERR_UNAUTHORIZED_OR_EXPIRED for method: %s", method)
            raise SessionExpiredError(f"Session expired while calling {method}")

        return data

    def _get_sysauth_cookie(self) -> Optional[str]:
        """Extract sysauth cookie from session cookie jar."""
        for cookie in self.session.cookies:
            if cookie.name == "sysauth" and cookie.domain == self.router_ip:
                return cookie.value

        for cookie in self.session.cookies:
            if cookie.name == "sysauth":
                return cookie.value

        return None

    def _set_sysauth_cookie(self) -> None:
        """Explicitly set sysauth cookie in session cookie jar."""
        if self.sysauth:
            self.session.cookies.set(
                "sysauth",
                self.sysauth,
                domain=self.router_ip,
                path="/"
            )

    # ==========================================================================
    # Authentication Sequence
    # ==========================================================================

    def pre_login(self) -> Dict[str, Any]:
        """Step 1: Perform preLogin handshake check."""
        logger.debug("Executing preLogin against %s...", self.router_ip)
        response = self._request("preLogin")
        if response.get("status") != "OK":
            msg = response.get("message", "Unknown error")
            raise JioRouterError(f"preLogin failed: {msg}")
        return response

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
        """
        Step 2: Submit credentials.
        Extracts bearer token, sysauth cookie, and handles ERR_LOGIN_DUPLICATE_ADMIN.
        """
        user = username or self.username
        pwd = password or self.password

        if not pwd:
            raise ValueError("Router password is required for authentication.")

        logger.info("Executing login for user '%s' on %s...", user, self.router_ip)

        # Clear any previous credentials
        self.bearer = None
        self.sysauth = None
        self.logged_id = None

        response = self._request(
            "login",
            {
                "username": user,
                "password": pwd
            }
        )

        # Case A: Normal successful login
        if response.get("status") == "OK":
            results = response.get("results", {})
            token = results.get("token")
            if not token:
                raise JioRouterError("Login succeeded but router did not return a token.")

            self.logged_id = results.get("loggedId")

            # Verified router format: BEARER-SYSAUTH
            if "-" in token:
                self.bearer, token_sysauth = token.split("-", 1)
                self.sysauth = token_sysauth
            else:
                self.bearer = token
                self.sysauth = self._get_sysauth_cookie()

            self._set_sysauth_cookie()
            logger.info("Login credential handshake succeeded (Bearer received).")
            return response

        # Case B: Existing admin session (ERR_LOGIN_DUPLICATE_ADMIN)
        if response.get("code") == "ERR_LOGIN_DUPLICATE_ADMIN":
            results = response.get("results", {})
            self.logged_id = results.get("loggedId")
            token = results.get("token")

            if not self.logged_id or not token:
                raise JioRouterError("Duplicate admin reported without required loggedId or token.")

            self.bearer = token
            self.sysauth = self._get_sysauth_cookie()
            self._set_sysauth_cookie()
            logger.warning("Existing admin session detected on router (loggedId: %s).", self.logged_id)
            return response

        error_msg = response.get("message", "Unknown login failure")
        raise JioRouterError(f"Login failed: {error_msg}")

    def post_login(self, logged_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Step 3: Finalize session binding or force login.
        Must be called after login() for both normal and duplicate admin sessions.
        """
        if not self.bearer:
            raise ValueError("Cannot perform postLogin without an active bearer token.")

        logger.debug("Executing postLogin...")
        params: Dict[str, Any] = {
            "authHeader": f"Bearer {self.bearer}"
        }

        active_logged_id = logged_id or self.logged_id
        if active_logged_id:
            params["loggedId"] = active_logged_id

        response = self._request("postLogin", params)
        if response.get("status") != "OK":
            msg = response.get("message", "Unknown error")
            raise JioRouterError(f"postLogin failed: {msg}")

        logger.info("postLogin successful (session bound).")
        return response

    def get_session_status(self) -> Dict[str, Any]:
        """Step 4: Verify that current session is recognized as active."""
        response = self._request("getSessionStatus")
        if response.get("status") != "OK":
            msg = response.get("message", "Session invalid")
            raise SessionExpiredError(f"Session status check failed: {msg}")
        return response

    def logout(self) -> Dict[str, Any]:
        """Terminate active session on physical router."""
        if not self.bearer:
            logger.warning("Logout called but no bearer token is present.")
            return {"status": "OK", "code": "NO_SESSION"}

        logger.info("Sending logout request to router...")
        response = self._request(
            "logout",
            {
                "authHeader": f"Bearer {self.bearer}"
            }
        )

        if response.get("status") == "OK" and response.get("code") == "OK_LOGOUT":
            logger.info("Router confirmed clean logout (OK_LOGOUT).")
        else:
            logger.warning("Router logout response not confirmed: %s", response)

        self.bearer = None
        self.sysauth = None
        self.logged_id = None
        return response

    # ==========================================================================
    # Device & Traffic Discovery
    # ==========================================================================

    def get_wireless_clients(self) -> List[Dict[str, Any]]:
        """Retrieve connected wireless clients with interface counters."""
        response = self._request("getWirelessClients")
        if response.get("status") != "OK":
            msg = response.get("message", "Failed to retrieve wireless clients")
            raise JioRouterError(f"getWirelessClients failed: {msg}")
        return response.get("results", [])

    def get_lan_clients(self) -> List[Dict[str, Any]]:
        """Retrieve LAN/Ethernet clients with IP and hostname mapping."""
        response = self._request("getLanClients")
        if response.get("status") != "OK":
            msg = response.get("message", "Failed to retrieve LAN clients")
            raise JioRouterError(f"getLanClients failed: {msg}")
        return response.get("results", [])

    def get_clients(self) -> List[Dict[str, Any]]:
        """
        Retrieve and merge wireless and LAN clients matching on normalized MAC address.
        """
        wireless = self.get_wireless_clients()
        lan = self.get_lan_clients()

        lan_by_mac = {
            client["macAddress"].lower(): client
            for client in lan
            if client.get("macAddress")
        }

        clients = []
        for client in wireless:
            mac = client.get("macAddress", "").lower()
            lan_info = lan_by_mac.get(mac, {})

            clients.append({
                "macAddress": mac,
                "ipv4Address": lan_info.get("ipv4Address"),
                "ipv6Address": lan_info.get("ipv6Address"),
                "hostName": lan_info.get("hostName") or "Device-" + mac[-5:],
                "radio": client.get("radio"),
                "ssid": client.get("ssid"),
                "apName": client.get("apName"),
                "bytesRx": int(client.get("bytesRx", 0)),
                "bytesTx": int(client.get("bytesTx", 0)),
                "pktsRx": int(client.get("pktsRx", 0)),
                "pktsTx": int(client.get("pktsTx", 0)),
                "errorsRx": int(client.get("errorsRx", 0)),
                "errorsTx": int(client.get("errorsTx", 0)),
                "droppedRx": int(client.get("droppedRx", 0)),
                "droppedTx": int(client.get("droppedTx", 0)),
                "timeConnected": client.get("timeConnected")
            })

        return clients
