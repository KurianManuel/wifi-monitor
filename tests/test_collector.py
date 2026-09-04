"""
Unit tests for the Real Jio Router Collector.

Tests:
- calculate_delta() correct delta and reset detection
- DataCollector mock-mode returns empty device list (no network calls)
- DataCollector real-mode polls get_clients() and stores samples
- DataCollector handles SessionExpiredError with re-authentication
- DataCollector re-authentication failure causes cycle to be skipped
- CollectorThread starts, runs one cycle, and stops cleanly
- Direction semantics: download = delta(bytesTx), upload = delta(bytesRx)
"""

import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

import database
from collector import DataCollector, CollectorThread, calculate_delta, start_collector
from login import JioSession, PlaceholderJioAuth
from logout import PlaceholderJioLogout
from router_api import SessionExpiredError


# ==============================================================================
# calculate_delta() Tests
# ==============================================================================

def test_calculate_delta_normal():
    """Standard positive delta."""
    assert calculate_delta(1000, 600) == 400


def test_calculate_delta_no_previous():
    """First observation — previous is None, delta must be 0."""
    assert calculate_delta(5000, None) == 0


def test_calculate_delta_counter_reset():
    """Counter decreases (router reboot) — delta must be 0, no negative values."""
    assert calculate_delta(100, 9999) == 0


def test_calculate_delta_no_change():
    """Counter unchanged between samples — delta is 0."""
    assert calculate_delta(500, 500) == 0


def test_calculate_delta_large():
    """Large delta, typical of overnight traffic."""
    assert calculate_delta(5_000_000_000, 1_000_000_000) == 4_000_000_000


# ==============================================================================
# DataCollector — Mock Mode
# ==============================================================================

def test_datacollector_mock_mode_returns_empty():
    """In mock mode, _poll_raw_data() must return empty list without network calls."""
    with patch("collector.config") as mock_cfg:
        mock_cfg.is_mock = True
        mock_cfg.ROUTER_HOST = "192.168.29.1"
        mock_cfg.ROUTER_USERNAME = "admin"
        mock_cfg.ROUTER_PASSWORD = ""
        mock_cfg.COLLECTION_INTERVAL = 60

        auth = PlaceholderJioAuth("192.168.29.1", "admin")
        logout = PlaceholderJioLogout("192.168.29.1")
        collector = DataCollector(auth_handler=auth, logout_handler=logout)

        result = collector._poll_raw_data()
        assert result == []


def test_datacollector_mock_collect_once_succeeds():
    """collect_once() in mock mode should return True (empty network, no errors)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        database.init_db(db_path)
        auth = PlaceholderJioAuth("192.168.29.1", "admin")
        logout = PlaceholderJioLogout("192.168.29.1")
        collector = DataCollector(auth_handler=auth, logout_handler=logout, db_path=db_path)

        result = collector.collect_once()
        assert result is True
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


# ==============================================================================
# DataCollector — Real Mode Device Polling
# ==============================================================================

def _make_fake_device(mac="aa:bb:cc:11:22:33", bytes_rx=500, bytes_tx=1000):
    return {
        "mac_address": mac,
        "hostname": "Test-Device",
        "ip_address": "192.168.29.50",
        "radio": "5GHz",
        "ssid": "JioFiber-5G",
        "ap": "AP1",
        "bytes_rx": bytes_rx,
        "bytes_tx": bytes_tx,
        "pkts_rx": 10,
        "pkts_tx": 20,
        "errors_rx": 0,
        "errors_tx": 0,
        "dropped_rx": 0,
        "dropped_tx": 0,
    }


def test_datacollector_real_mode_polls_clients():
    """In real mode, collect_once() calls _poll_raw_data() and inserts samples."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        database.init_db(db_path)

        auth = PlaceholderJioAuth("192.168.29.1", "admin")
        logout = PlaceholderJioLogout("192.168.29.1")
        collector = DataCollector(auth_handler=auth, logout_handler=logout, db_path=db_path)

        fake_device = _make_fake_device()
        with patch.object(collector, "_poll_raw_data", return_value=[fake_device]):
            result = collector.collect_once()

        assert result is True

        with database.get_db_connection(db_path) as conn:
            rows = conn.execute("SELECT * FROM traffic_samples").fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["mac_address"] == "AA:BB:CC:11:22:33"
        # First observation → both deltas are 0 (no prior baseline)
        assert row["download_bytes"] == 0
        assert row["upload_bytes"] == 0
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_datacollector_direction_semantics():
    """
    CRITICAL: download_bytes = delta(bytesTx), upload_bytes = delta(bytesRx).
    Verify semantics are not reversed across two collection cycles.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        database.init_db(db_path)

        auth = PlaceholderJioAuth("192.168.29.1", "admin")
        logout = PlaceholderJioLogout("192.168.29.1")
        collector = DataCollector(auth_handler=auth, logout_handler=logout, db_path=db_path)

        mac = "aa:bb:cc:11:22:33"

        # Cycle 1 — baseline (first observation, deltas = 0)
        dev1 = _make_fake_device(mac=mac, bytes_rx=1000, bytes_tx=2000)
        with patch.object(collector, "_poll_raw_data", return_value=[dev1]):
            collector.collect_once()

        # Cycle 2 — bytes_rx increases by 300, bytes_tx increases by 700
        dev2 = _make_fake_device(mac=mac, bytes_rx=1300, bytes_tx=2700)
        with patch.object(collector, "_poll_raw_data", return_value=[dev2]):
            collector.collect_once()

        with database.get_db_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM traffic_samples ORDER BY id"
            ).fetchall()

        assert len(rows) == 2
        second = dict(rows[1])

        # download = delta(bytesTx) = 2700 - 2000 = 700
        assert second["download_bytes"] == 700, \
            f"Expected download_bytes=700 but got {second['download_bytes']}"

        # upload = delta(bytesRx) = 1300 - 1000 = 300
        assert second["upload_bytes"] == 300, \
            f"Expected upload_bytes=300 but got {second['upload_bytes']}"

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_datacollector_counter_reset_handling():
    """Counter reset between cycles produces zero deltas, not negative values."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        database.init_db(db_path)

        auth = PlaceholderJioAuth("192.168.29.1", "admin")
        logout = PlaceholderJioLogout("192.168.29.1")
        collector = DataCollector(auth_handler=auth, logout_handler=logout, db_path=db_path)

        mac = "aa:bb:cc:11:22:33"

        # Cycle 1 — high counters
        dev1 = _make_fake_device(mac=mac, bytes_rx=9_000_000, bytes_tx=5_000_000)
        with patch.object(collector, "_poll_raw_data", return_value=[dev1]):
            collector.collect_once()

        # Cycle 2 — counter reset (values dropped back to near zero after router reboot)
        dev2 = _make_fake_device(mac=mac, bytes_rx=100, bytes_tx=200)
        with patch.object(collector, "_poll_raw_data", return_value=[dev2]):
            collector.collect_once()

        with database.get_db_connection(db_path) as conn:
            rows = conn.execute("SELECT * FROM traffic_samples ORDER BY id").fetchall()

        second = dict(rows[1])
        assert second["download_bytes"] == 0
        assert second["upload_bytes"] == 0
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


# ==============================================================================
# DataCollector — Session Expiry Handling
# ==============================================================================

def test_datacollector_session_expiry_triggers_reauth():
    """SessionExpiredError during _poll_raw_data triggers re-authentication."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        database.init_db(db_path)

        auth = PlaceholderJioAuth("192.168.29.1", "admin")
        logout = PlaceholderJioLogout("192.168.29.1")
        collector = DataCollector(auth_handler=auth, logout_handler=logout, db_path=db_path)

        fake_device = _make_fake_device()

        # First call raises SessionExpiredError; second (post re-auth) succeeds
        call_count = {"n": 0}
        def poll_side_effect():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise SessionExpiredError("Session expired mid-poll")
            return [fake_device]

        with patch.object(collector, "_poll_raw_data", side_effect=poll_side_effect), \
             patch.object(collector, "_handle_session_expiry", return_value=True) as mock_reauth:
            result = collector.collect_once()

        assert result is True
        mock_reauth.assert_called_once()
        assert call_count["n"] == 2
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_datacollector_reauth_failure_skips_cycle():
    """If re-authentication fails after session expiry, collect_once() returns False."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        database.init_db(db_path)

        auth = PlaceholderJioAuth("192.168.29.1", "admin")
        logout = PlaceholderJioLogout("192.168.29.1")
        collector = DataCollector(auth_handler=auth, logout_handler=logout, db_path=db_path)

        with patch.object(collector, "_poll_raw_data", side_effect=SessionExpiredError("expired")), \
             patch.object(collector, "_handle_session_expiry", return_value=False):
            result = collector.collect_once()

        assert result is False

        with database.get_db_connection(db_path) as conn:
            rows = conn.execute("SELECT * FROM traffic_samples").fetchall()
        assert len(rows) == 0
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


# ==============================================================================
# CollectorThread Tests
# ==============================================================================

def test_collector_thread_runs_and_stops():
    """CollectorThread starts, calls collect_once, and stops cleanly."""
    mock_collector = MagicMock(spec=DataCollector)
    mock_collector.collect_once.return_value = True

    thread = CollectorThread(collector=mock_collector, interval=1)
    thread.start()
    time.sleep(0.5)
    thread.stop()
    thread.join(timeout=3.0)

    assert not thread.is_alive(), "CollectorThread should have stopped."
    assert mock_collector.collect_once.call_count >= 1


def test_start_collector_returns_running_thread():
    """start_collector() returns a running CollectorThread daemon."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        database.init_db(db_path)

        with patch("collector.DataCollector.collect_once", return_value=True):
            thread = start_collector(db_path=db_path)

        assert isinstance(thread, CollectorThread)
        assert thread.is_alive()
        assert thread.daemon is True

        thread.stop()
        thread.join(timeout=3.0)
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
