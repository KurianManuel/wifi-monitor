"""
Collector module for Jio WiFi Data Tracker.

Coordinates data collection:
1. Validates or establishes session
2. Collects device counters & network statistics
3. Calculates deltas with strict direction semantics:
   - download_bytes = delta of router current_tx
   - upload_bytes   = delta of router current_rx
4. Handles counter resets and preserves SQLite samples
5. Catches and logs all errors without crashing the service
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import database
from config import config
from login import JioAuthInterface, JioSession, PlaceholderJioAuth
from logout import JioLogoutInterface, PlaceholderJioLogout

logger = logging.getLogger("jio_wifi_tracker.collector")


def calculate_delta(current: int, previous: Optional[int]) -> int:
    """
    Calculate counter delta with reset detection.
    
    If counter decreases (e.g. router reboot or interface reset),
    treat it as a counter reset: return 0 (or current if base) without
    creating negative traffic or artificial spikes.
    """
    if previous is None:
        return 0
    if current < previous:
        logger.warning("Counter reset detected: previous=%d, current=%d. Setting delta to 0.", previous, current)
        return 0
    return current - previous


class DataCollector:
    """Coordinates periodic collection cycles."""

    def __init__(
        self,
        auth_handler: Optional[JioAuthInterface] = None,
        logout_handler: Optional[JioLogoutInterface] = None,
        db_path: Optional[str] = None
    ):
        self.auth = auth_handler or PlaceholderJioAuth(config.ROUTER_HOST, config.ROUTER_USERNAME)
        self.logout = logout_handler or PlaceholderJioLogout(config.ROUTER_HOST)
        self.db_path = db_path
        self.session: Optional[JioSession] = None
        self._last_device_counters: Dict[str, Dict[str, int]] = {}

    def ensure_session(self) -> bool:
        """Ensure an authenticated session exists."""
        try:
            if not self.session or not self.auth.is_authenticated():
                logger.info("Establishing router session...")
                self.session = self.auth.login()
            return self.session is not None and self.session.is_valid()
        except Exception as e:
            logger.error("Failed to establish router session: %s", e, exc_info=True)
            return False

    def collect_once(self) -> bool:
        """
        Execute a single collection cycle.
        Survives exceptions without crashing the caller.
        """
        try:
            if not self.ensure_session():
                logger.warning("Collection skipped: No active router session.")
                return False

            timestamp = datetime.now().isoformat()
            
            # In Phase 1 foundation, when running in mock mode or placeholder,
            # this demonstrates the delta pipeline and database insertion.
            devices_data = self._poll_raw_data()
            for dev in devices_data:
                mac = dev["mac_address"].upper()
                curr_rx = dev["bytes_rx"]
                curr_tx = dev["bytes_tx"]
                
                prev = self._last_device_counters.get(mac)
                prev_rx = prev["bytes_rx"] if prev else None
                prev_tx = prev["bytes_tx"] if prev else None

                # CRITICAL SEMANTICS:
                # download_bytes = delta of router current_tx
                # upload_bytes   = delta of router current_rx
                delta_tx = calculate_delta(curr_tx, prev_tx)
                delta_rx = calculate_delta(curr_rx, prev_rx)

                download_bytes = delta_tx
                upload_bytes = delta_rx

                # Update cache
                self._last_device_counters[mac] = {
                    "bytes_rx": curr_rx,
                    "bytes_tx": curr_tx
                }

                # Save sample to SQLite
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
                    "dropped_tx": dev.get("dropped_tx", 0)
                }
                database.insert_sample(sample, self.db_path)
                
                # Update device info
                database.upsert_device({
                    "mac_address": mac,
                    "hostname": dev.get("hostname", "Device-" + mac[-5:]),
                    "ip_address": dev.get("ip_address", "192.168.29.50"),
                    "radio": dev.get("radio", "5GHz"),
                    "ssid": dev.get("ssid", "JioFiber-5G"),
                    "ap": dev.get("ap", "AP1"),
                    "last_seen": timestamp,
                    "is_active": True
                }, self.db_path)

            logger.debug("Collection completed successfully at %s", timestamp)
            return True

        except Exception as e:
            logger.error("Error during collection cycle: %s", e, exc_info=True)
            return False

    def _poll_raw_data(self) -> List[Dict[str, Any]]:
        """
        Placeholder polling method.
        Real Jio polling will be hooked during Phase 10.
        """
        return []
