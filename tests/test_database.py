"""
Unit tests for database.py SQLite storage and queries.
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
import pytest

import database


@pytest.fixture
def temp_db():
    """Create a temporary database file for test isolation."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database.init_db(path)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


def test_init_db_creates_tables_and_indexes(temp_db):
    """Verify that tables and indexes are created properly."""
    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        
        # Check tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row["name"] for row in cursor.fetchall()}
        assert "traffic_samples" in tables
        assert "devices" in tables

        # Check indexes
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
        indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_samples_timestamp" in indexes
        assert "idx_samples_mac" in indexes
        assert "idx_samples_timestamp_mac" in indexes


def test_insert_sample_preserves_direction_semantics(temp_db):
    """
    Verify sample insertion:
    download_bytes = delta of router current_tx
    upload_bytes = delta of router current_rx
    """
    sample = {
        "timestamp": "2026-09-04T10:00:00+05:30",
        "mac_address": "AA:BB:CC:DD:EE:01",
        "bytes_rx": 1000,
        "bytes_tx": 5000,
        "download_bytes": 5000,  # from current_tx delta
        "upload_bytes": 1000,    # from current_rx delta
        "pkts_rx": 10,
        "pkts_tx": 50,
        "errors_rx": 0,
        "errors_tx": 0,
        "dropped_rx": 0,
        "dropped_tx": 0,
    }
    row_id = database.insert_sample(sample, temp_db)
    assert row_id > 0

    latest = database.get_latest_sample_for_mac("AA:BB:CC:DD:EE:01", temp_db)
    assert latest is not None
    assert latest["mac_address"] == "AA:BB:CC:DD:EE:01"
    assert latest["download_bytes"] == 5000
    assert latest["upload_bytes"] == 1000


def test_total_usage_between(temp_db):
    """Test aggregation query between timestamp bounds."""
    # Insert 2 samples
    s1 = {
        "timestamp": "2026-09-04T08:00:00+05:30",
        "mac_address": "AA:BB:CC:DD:EE:01",
        "bytes_rx": 200, "bytes_tx": 800,
        "download_bytes": 800, "upload_bytes": 200
    }
    s2 = {
        "timestamp": "2026-09-04T09:00:00+05:30",
        "mac_address": "AA:BB:CC:DD:EE:02",
        "bytes_rx": 300, "bytes_tx": 700,
        "download_bytes": 700, "upload_bytes": 300
    }
    database.insert_sample(s1, temp_db)
    database.insert_sample(s2, temp_db)

    usage = database.get_total_usage_between(
        "2026-09-04T07:00:00+05:30",
        "2026-09-04T10:00:00+05:30",
        temp_db
    )
    assert usage["download_bytes"] == 1500
    assert usage["upload_bytes"] == 500
    assert usage["total_bytes"] == 2000


def test_network_stats_summary(temp_db):
    """Test network counters aggregation."""
    s1 = {
        "timestamp": "2026-09-04T08:00:00+05:30",
        "mac_address": "AA:BB:CC:DD:EE:01",
        "bytes_rx": 100, "bytes_tx": 200,
        "download_bytes": 200, "upload_bytes": 100,
        "pkts_rx": 10, "pkts_tx": 20,
        "errors_rx": 1, "errors_tx": 2,
        "dropped_rx": 3, "dropped_tx": 4
    }
    database.insert_sample(s1, temp_db)

    stats = database.get_network_stats_summary(temp_db)
    assert stats["bytes_rx"] == 100
    assert stats["bytes_tx"] == 200
    assert stats["packets_rx"] == 10
    assert stats["packets_tx"] == 20
    assert stats["errors_rx"] == 1
    assert stats["errors_tx"] == 2
    assert stats["dropped_rx"] == 3
    assert stats["dropped_tx"] == 4
