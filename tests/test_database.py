"""
Unit tests for database.py SQLite storage, retention, and inspection queries (Phase 3).
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


def test_retention_purge(temp_db):
    """Test purge_old_samples retention logic."""
    old_time = (datetime.now() - timedelta(days=40)).isoformat()
    recent_time = (datetime.now() - timedelta(days=2)).isoformat()

    database.insert_sample({"timestamp": old_time, "mac_address": "AA:11", "download_bytes": 100}, temp_db)
    database.insert_sample({"timestamp": recent_time, "mac_address": "AA:22", "download_bytes": 200}, temp_db)

    # Retention = 0 means do not purge
    deleted_zero = database.purge_old_samples(0, temp_db)
    assert deleted_zero == 0

    # Retention = 30 days purges sample from 40 days ago
    deleted_purged = database.purge_old_samples(30, temp_db)
    assert deleted_purged == 1

    # Recent sample still exists
    remaining = database.inspect_latest_samples(10, temp_db)
    assert len(remaining) == 1
    assert remaining[0]["mac_address"] == "AA:22"


def test_database_inspection_helpers(temp_db):
    """Verify all database inspection utilities."""
    # Test tables & schema inspection
    tables = database.inspect_tables(temp_db)
    assert "traffic_samples" in tables
    assert "devices" in tables

    schema = database.inspect_schema(temp_db)
    assert "traffic_samples" in schema
    assert "idx_samples_timestamp_mac" in schema

    # Test device count
    assert database.inspect_device_count(temp_db) == 0
    database.upsert_device({"mac_address": "AA:BB:CC:11:22:33", "hostname": "Phone"}, temp_db)
    assert database.inspect_device_count(temp_db) == 1

    # Test latest samples
    now_iso = datetime.now().isoformat()
    database.insert_sample({"timestamp": now_iso, "mac_address": "AA:BB:CC:11:22:33", "download_bytes": 50, "upload_bytes": 25}, temp_db)
    latest = database.inspect_latest_samples(5, temp_db)
    assert len(latest) == 1
    assert latest[0]["mac_address"] == "AA:BB:CC:11:22:33"

    # Test daily and hourly inspection
    daily = database.inspect_daily_usage(7, temp_db)
    assert len(daily) >= 1
    assert daily[0]["download_bytes"] == 50

    hourly = database.inspect_hourly_usage(now_iso[:10], temp_db)
    assert len(hourly) >= 1

    # Test device history
    dev_hist = database.inspect_device_history("AA:BB:CC:11:22:33", 7, temp_db)
    assert len(dev_hist) >= 1
    assert dev_hist[0]["total_bytes"] == 75


def test_devices_table_has_new_columns(temp_db):
    """Verify first_seen and time_connected columns exist in devices table."""
    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(devices);")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "first_seen" in columns
        assert "time_connected" in columns


def test_upsert_device_with_first_seen_and_time_connected(temp_db):
    """Test upsert_device supports first_seen and time_connected fields."""
    now = datetime.now().isoformat()
    router_time = "2026-09-04T10:30:00+05:30"

    database.upsert_device({
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "hostname": "TestDevice",
        "first_seen": now,
        "time_connected": router_time,
    }, temp_db)

    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT first_seen, time_connected FROM devices WHERE mac_address = ?", ("AA:BB:CC:DD:EE:FF",))
        row = cursor.fetchone()
        assert row["first_seen"] == now
        assert row["time_connected"] == router_time


def test_upsert_device_preserves_existing_first_seen(temp_db):
    """Test that upsert doesn't overwrite existing first_seen with newer value."""
    old_time = (datetime.now() - timedelta(days=10)).isoformat()
    new_time = datetime.now().isoformat()

    # First insert with old first_seen
    database.upsert_device({
        "mac_address": "AA:BB:CC:DD:EE:01",
        "hostname": "OldDevice",
        "first_seen": old_time,
        "time_connected": "2026-09-04T10:30:00+05:30",
    }, temp_db)

    # Update with newer first_seen - should preserve the old one
    database.upsert_device({
        "mac_address": "AA:BB:CC:DD:EE:01",
        "hostname": "OldDevice",
        "first_seen": new_time,
        "time_connected": "2026-09-04T11:30:00+05:30",
    }, temp_db)

    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT first_seen, time_connected FROM devices WHERE mac_address = ?", ("AA:BB:CC:DD:EE:01",))
        row = cursor.fetchone()
        assert row["first_seen"] == old_time  # Preserved
        assert row["time_connected"] == "2026-09-04T11:30:00+05:30"  # Updated


def test_upsert_device_with_null_time_connected(temp_db):
    """Test upsert_device handles NULL time_connected correctly."""
    database.upsert_device({
        "mac_address": "AA:BB:CC:DD:EE:02",
        "hostname": "NoRouterTime",
        "first_seen": datetime.now().isoformat(),
        "time_connected": None,
    }, temp_db)

    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT time_connected FROM devices WHERE mac_address = ?", ("AA:BB:CC:DD:EE:02",))
        row = cursor.fetchone()
        assert row["time_connected"] is None


def test_migration_on_existing_database(temp_db):
    """Test migration adds columns and populates first_seen from last_seen for existing rows without traffic samples."""
    # Simulate an old database by creating devices table without new columns
    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        # Drop and recreate old-style devices table
        cursor.execute("DROP TABLE devices;")
        cursor.execute("""
            CREATE TABLE devices (
                mac_address TEXT PRIMARY KEY,
                hostname TEXT,
                ip_address TEXT,
                radio TEXT,
                ssid TEXT,
                ap TEXT,
                last_seen TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );
        """)
        # Insert old device (no traffic samples for this device)
        old_time = (datetime.now() - timedelta(days=5)).isoformat()
        cursor.execute("""
            INSERT INTO devices (mac_address, hostname, last_seen, is_active)
            VALUES (?, ?, ?, 1)
        """, ("AA:BB:CC:OLD:DE:VICE", "OldDevice", old_time))
        conn.commit()

    # Now run init_db which should trigger migration
    database.init_db(temp_db)

    # Verify migration worked
    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(devices);")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "first_seen" in columns
        assert "time_connected" in columns

        cursor.execute("SELECT mac_address, last_seen, first_seen, time_connected FROM devices WHERE mac_address = ?", ("AA:BB:CC:OLD:DE:VICE",))
        row = cursor.fetchone()
        assert row["mac_address"] == "AA:BB:CC:OLD:DE:VICE"
        assert row["first_seen"] == old_time  # Migrated from last_seen (no traffic samples)
        assert row["time_connected"] is None  # NULL for existing rows


def test_migration_uses_earliest_traffic_sample(temp_db):
    """Test migration uses earliest traffic_samples timestamp when available."""
    # Simulate old database with device that has traffic samples
    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE devices;")
        cursor.execute("DROP TABLE traffic_samples;")
        cursor.execute("""
            CREATE TABLE devices (
                mac_address TEXT PRIMARY KEY,
                hostname TEXT,
                last_seen TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );
        """)
        cursor.execute("""
            CREATE TABLE traffic_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                mac_address TEXT NOT NULL,
                download_bytes INTEGER NOT NULL DEFAULT 0,
                upload_bytes INTEGER NOT NULL DEFAULT 0
            );
        """)
        # Device with last_seen = Sep 15, but traffic from Sep 1 and Sep 10
        cursor.execute("INSERT INTO devices (mac_address, hostname, last_seen, is_active) VALUES (?, ?, ?, 1)",
                       ("AA:BB:CC:OLD:DE:VICE", "OldDevice", "2026-09-15T10:00:00"))
        cursor.execute("INSERT INTO traffic_samples (timestamp, mac_address, download_bytes, upload_bytes) VALUES (?, ?, 100, 50)",
                       ("2026-09-01T08:00:00", "AA:BB:CC:OLD:DE:VICE"))
        cursor.execute("INSERT INTO traffic_samples (timestamp, mac_address, download_bytes, upload_bytes) VALUES (?, ?, 200, 100)",
                       ("2026-09-10T08:00:00", "AA:BB:CC:OLD:DE:VICE"))
        conn.commit()

    # Run migration
    database.init_db(temp_db)

    # Verify first_seen uses earliest traffic sample (Sep 1), not last_seen (Sep 15)
    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT mac_address, last_seen, first_seen FROM devices WHERE mac_address = ?", ("AA:BB:CC:OLD:DE:VICE",))
        row = cursor.fetchone()
        assert row["first_seen"] == "2026-09-01T08:00:00"  # Earliest traffic sample
        assert row["last_seen"] == "2026-09-15T10:00:00"


def test_migration_idempotent(temp_db):
    """Test migration is safe to run multiple times."""
    # Run init_db twice
    database.init_db(temp_db)
    database.init_db(temp_db)

    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(devices);")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "first_seen" in columns
        assert "time_connected" in columns

        # No errors, columns exist only once
        cursor.execute("SELECT COUNT(*) as cnt FROM pragma_table_info('devices') WHERE name IN ('first_seen', 'time_connected');")
        row = cursor.fetchone()
        assert row["cnt"] == 2


def test_existing_device_rows_preserved_after_migration(temp_db):
    """Test existing device data remains intact after migration."""
    # Create old-style table with multiple devices
    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE devices;")
        cursor.execute("""
            CREATE TABLE devices (
                mac_address TEXT PRIMARY KEY,
                hostname TEXT,
                ip_address TEXT,
                radio TEXT,
                ssid TEXT,
                ap TEXT,
                last_seen TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );
        """)
        devices = [
            ("AA:BB:CC:11:11:11", "Device1", "192.168.1.10", "5G", "JioFiber", "AP1", (datetime.now() - timedelta(days=10)).isoformat(), 1),
            ("AA:BB:CC:22:22:22", "Device2", "192.168.1.11", "2.4G", "JioFiber", "AP1", (datetime.now() - timedelta(days=5)).isoformat(), 1),
            ("AA:BB:CC:33:33:33", "Device3", "192.168.1.12", "5G", "JioFiber", "AP2", (datetime.now() - timedelta(days=1)).isoformat(), 0),
        ]
        for d in devices:
            cursor.execute("""
                INSERT INTO devices (mac_address, hostname, ip_address, radio, ssid, ap, last_seen, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, d)
        conn.commit()

    # Run migration
    database.init_db(temp_db)

    # Verify all devices preserved with correct data
    with database.get_db_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT mac_address, hostname, ip_address, radio, ssid, ap, last_seen, is_active, first_seen, time_connected FROM devices ORDER BY mac_address")
        rows = cursor.fetchall()
        assert len(rows) == 3
        for i, row in enumerate(rows):
            expected = devices[i]
            assert row["mac_address"] == expected[0]
            assert row["hostname"] == expected[1]
            assert row["ip_address"] == expected[2]
            assert row["radio"] == expected[3]
            assert row["ssid"] == expected[4]
            assert row["ap"] == expected[5]
            assert row["last_seen"] == expected[6]
            assert row["is_active"] == expected[7]
            assert row["first_seen"] == expected[6]  # Migrated from last_seen
            assert row["time_connected"] is None  # NULL for old rows
