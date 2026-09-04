"""
Real Jio Router Collector for Jio WiFi Data Tracker.

Coordinates periodic data collection:
  1. Validates or re-establishes authenticated session via JioRouterAuth
  2. Polls connected clients via JioRouterClient.get_clients()
  3. Calculates per-device traffic deltas with strict direction semantics:
       download_bytes = delta of router current_tx   (device sent → router received)
       upload_bytes   = delta of router current_rx   (device received ← router sent)
  4. Detects and handles counter resets (router reboot / interface flap)
  5. Handles SessionExpiredError with automatic re-authentication
  6. Persists samples and device metadata to SQLite
  7. Catches and logs all errors without crashing the service

Direction semantics are permanently locked:
  download_bytes = delta(bytesTx)   ← router field 'bytesTx' (device transmitted)
  upload_bytes   = delta(bytesRx)   ← router field 'bytesRx' (device received)
DO NOT REVERSE THIS.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import database
from config import config
from login import JioAuthInterface, JioRouterAuth, JioSession, PlaceholderJioAuth
from logout import JioLogoutInterface, JioRouterLogout, PlaceholderJioLogout
from router_api import JioRouterClient, SessionExpiredError

logger = logging.getLogger("jio_wifi_tracker.collector")


# ==============================================================================
# Delta Calculation
# ==============================================================================

def calculate_delta(current: int, previous: Optional[int]) -> int:
    """
    Calculate counter delta with counter-reset detection.

    If the current value is less than the previous value (router reboot or
    interface reset), treat as a counter reset: return 0 to avoid negative
    traffic or artificial spikes. Only valid positive deltas are returned.
    """
    if previous is None:
        # First observation — no prior reference point, delta is undefined
        return 0
    if current < previous:
        logger.warning(
            "Counter reset detected: previous=%d, current=%d. Setting delta to 0.",
            previous, current
        )
        return 0
    return current - previous


# ==============================================================================
# Data Collector
# ==============================================================================

class DataCollector:
    """
    Coordinates periodic collection cycles against a JioFiber/JioAirFiber router.

    In 'real' mode: uses JioRouterAuth + JioRouterClient.get_clients().
    In 'mock' mode: uses PlaceholderJioAuth and returns empty device list (no network calls).
    """

    def __init__(
        self,
        auth_handler: Optional[JioAuthInterface] = None,
        logout_handler: Optional[JioLogoutInterface] = None,
        db_path: Optional[str] = None
    ):
        self.db_path = db_path

        # Wire handlers based on mode or injected dependencies (for testing)
        if auth_handler is not None:
            self.auth = auth_handler
        elif config.is_mock:
            logger.info("Collector running in MOCK mode — no real router calls.")
            self.auth = PlaceholderJioAuth(config.ROUTER_HOST, config.ROUTER_USERNAME)
        else:
            logger.info(
                "Collector running in REAL mode — targeting router: %s", config.ROUTER_HOST
            )
            self.auth = JioRouterAuth(
                router_host=config.ROUTER_HOST,
                username=config.ROUTER_USERNAME,
                password=config.ROUTER_PASSWORD,
            )

        if logout_handler is not None:
            self.logout_handler = logout_handler
        elif config.is_mock:
            self.logout_handler = PlaceholderJioLogout(config.ROUTER_HOST)
        else:
            self.logout_handler = JioRouterLogout(router_host=config.ROUTER_HOST)

        self.session: Optional[JioSession] = None
        # Per-device cache of last observed counters: {mac: {"bytes_rx": int, "bytes_tx": int, ...}}
        self._last_device_counters: Dict[str, Dict[str, int]] = {}

    # --------------------------------------------------------------------------
    # Session Management
    # --------------------------------------------------------------------------

    def ensure_session(self) -> bool:
        """Ensure an authenticated session exists, re-authenticating if needed."""
        try:
            if not self.auth.is_authenticated():
                logger.info("No active session. Authenticating with router...")
                self.session = self.auth.login()
            else:
                self.session = self.auth.get_session()

            if self.session and self.session.is_valid():
                return True

            logger.warning("Session establishment returned no valid session.")
            return False

        except Exception as e:
            logger.error("Failed to establish router session: %s", e, exc_info=True)
            return False

    def _handle_session_expiry(self) -> bool:
        """Force a fresh authentication after detecting session expiry."""
        logger.warning("Session expired. Invalidating and forcing re-authentication...")
        self.auth.invalidate_session()
        self.session = None
        try:
            self.session = self.auth.login(force_refresh=True)
            if self.session and self.session.is_valid():
                logger.info("Re-authentication successful after session expiry.")
                return True
            logger.error("Re-authentication failed: login returned no valid session.")
            return False
        except Exception as e:
            logger.error("Re-authentication failed: %s", e, exc_info=True)
            return False

    # --------------------------------------------------------------------------
    # Real Router Polling
    # --------------------------------------------------------------------------

    def _poll_raw_data(self) -> List[Dict[str, Any]]:
        """
        Poll connected clients from the real Jio router.

        Returns a list of normalized device dicts with fields:
          mac_address, hostname, ip_address, radio, ssid, ap,
          bytes_rx, bytes_tx, pkts_rx, pkts_tx,
          errors_rx, errors_tx, dropped_rx, dropped_tx

        In mock mode, returns an empty list (no network calls).
        Raises SessionExpiredError if the router rejects the current session.
        """
        if config.is_mock:
            return []

        # Retrieve active session credentials
        active_session = self.auth.get_session()
        if not active_session or not active_session.is_valid():
            raise SessionExpiredError("No valid session available for polling.")

        # Build router client with current credentials
        client = JioRouterClient(
            router_ip=config.ROUTER_HOST,
            username=config.ROUTER_USERNAME,
            password=config.ROUTER_PASSWORD,
        )
        client.bearer = active_session.bearer
        client.sysauth = active_session.sysauth
        client.logged_id = active_session.logged_id
        client._set_sysauth_cookie()

        # Fetch merged wireless + LAN clients
        raw_clients = client.get_clients()

        # Normalize field names to internal snake_case convention
        normalized = []
        for c in raw_clients:
            mac = (c.get("macAddress") or "").lower()
            if not mac:
                continue

            normalized.append({
                "mac_address": mac,
                "hostname": c.get("hostName") or f"Device-{mac[-5:]}",
                "ip_address": c.get("ipv4Address") or "",
                "radio": c.get("radio") or "",
                "ssid": c.get("ssid") or "",
                "ap": c.get("apName") or "",
                # Raw cumulative counters from router
                "bytes_rx": int(c.get("bytesRx", 0)),
                "bytes_tx": int(c.get("bytesTx", 0)),
                "pkts_rx": int(c.get("pktsRx", 0)),
                "pkts_tx": int(c.get("pktsTx", 0)),
                "errors_rx": int(c.get("errorsRx", 0)),
                "errors_tx": int(c.get("errorsTx", 0)),
                "dropped_rx": int(c.get("droppedRx", 0)),
                "dropped_tx": int(c.get("droppedTx", 0)),
            })

        return normalized

    # --------------------------------------------------------------------------
    # Collection Cycle
    # --------------------------------------------------------------------------

    def collect_once(self) -> bool:
        """
        Execute a single collection cycle.

        - Ensures session is authenticated
        - Polls raw device data
        - Computes traffic deltas per device
        - Saves samples and device metadata to SQLite
        - Returns True on success, False on failure
        - Survives all exceptions without crashing the caller
        """
        try:
            if not self.ensure_session():
                logger.warning("Collection skipped: no active router session.")
                return False

            timestamp = datetime.now().isoformat()

            try:
                devices_data = self._poll_raw_data()
            except SessionExpiredError:
                logger.warning("Session expired during poll. Attempting re-authentication...")
                if not self._handle_session_expiry():
                    logger.error("Re-authentication failed. Skipping collection cycle.")
                    return False
                # Retry once after re-auth
                devices_data = self._poll_raw_data()

            for dev in devices_data:
                mac = dev["mac_address"].upper()

                curr_rx = dev["bytes_rx"]
                curr_tx = dev["bytes_tx"]

                prev = self._last_device_counters.get(mac)
                prev_rx = prev["bytes_rx"] if prev else None
                prev_tx = prev["bytes_tx"] if prev else None

                # ── CRITICAL DIRECTION SEMANTICS ──────────────────────────────
                # download_bytes = delta(bytesTx)  router bytesTx = device sent data
                # upload_bytes   = delta(bytesRx)  router bytesRx = device received data
                # DO NOT REVERSE THIS.
                download_bytes = calculate_delta(curr_tx, prev_tx)
                upload_bytes = calculate_delta(curr_rx, prev_rx)

                # Update per-device counter cache
                self._last_device_counters[mac] = {
                    "bytes_rx": curr_rx,
                    "bytes_tx": curr_tx,
                }

                # Persist traffic sample
                sample = {
                    "timestamp": timestamp,
                    "mac_address": mac,
                    "bytes_rx": curr_rx,
                    "bytes_tx": curr_tx,
                    "download_bytes": download_bytes,
                    "upload_bytes": upload_bytes,
                    "pkts_rx": dev.get("pkts_rx", 0),
                    "pkts_tx": dev.get("pkts_tx", 0),
                    "errors_rx": dev.get("errors_rx", 0),
                    "errors_tx": dev.get("errors_tx", 0),
                    "dropped_rx": dev.get("dropped_rx", 0),
                    "dropped_tx": dev.get("dropped_tx", 0),
                }
                database.insert_sample(sample, self.db_path)

                # Persist / update device metadata
                database.upsert_device(
                    {
                        "mac_address": mac,
                        "hostname": dev.get("hostname") or f"Device-{mac[-5:]}",
                        "ip_address": dev.get("ip_address") or "",
                        "radio": dev.get("radio") or "",
                        "ssid": dev.get("ssid") or "",
                        "ap": dev.get("ap") or "",
                        "last_seen": timestamp,
                        "is_active": True,
                    },
                    self.db_path,
                )

            if devices_data:
                logger.debug(
                    "Collection cycle completed: %d device(s) sampled at %s.",
                    len(devices_data), timestamp
                )
            else:
                logger.debug("Collection cycle completed: no devices found (mock or empty network).")

            return True

        except Exception as e:
            logger.error("Unexpected error during collection cycle: %s", e, exc_info=True)
            return False


# ==============================================================================
# Background Collection Loop
# ==============================================================================

class CollectorThread(threading.Thread):
    """
    Background daemon thread running the periodic collection loop.

    Runs forever with a configurable interval, surviving individual
    cycle failures without crashing the overall service.
    """

    def __init__(
        self,
        collector: Optional[DataCollector] = None,
        interval: Optional[int] = None,
        db_path: Optional[str] = None,
    ):
        super().__init__(daemon=True, name="jio-collector")
        self.collector = collector or DataCollector(db_path=db_path)
        self.interval = interval or config.COLLECTION_INTERVAL
        self._stop_event = threading.Event()

    def run(self) -> None:
        """Entry point for the collector thread."""
        logger.info(
            "Collector thread started. Collection interval: %ds (mode: %s).",
            self.interval, config.MODE
        )
        while not self._stop_event.is_set():
            try:
                self.collector.collect_once()
            except Exception as e:
                logger.error("Fatal error in collector loop: %s", e, exc_info=True)

            # Wait for the interval or until stop is requested
            self._stop_event.wait(timeout=self.interval)

        logger.info("Collector thread stopped.")

    def stop(self) -> None:
        """Signal the collector thread to stop gracefully."""
        self._stop_event.set()


def start_collector(db_path: Optional[str] = None) -> CollectorThread:
    """
    Create, start, and return a background CollectorThread.
    Convenience factory used by app.py.
    """
    thread = CollectorThread(db_path=db_path)
    thread.start()
    return thread
