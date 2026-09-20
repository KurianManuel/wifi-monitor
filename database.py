"""
Database layer for Jio WiFi Data Tracker.

Uses SQLite with WAL mode optimized for Raspberry Pi Zero 2 W.
Stores traffic samples and provides aggregated queries, retention pruning,
and comprehensive inspection utilities.

Critical Traffic Direction Semantics:
- download_bytes = delta of router current_tx
- upload_bytes = delta of router current_rx
DO NOT REVERSE THIS.
"""

import argparse
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from config import config

logger = logging.getLogger("jio_wifi_tracker.database")


def get_db_path(db_path: Optional[str] = None) -> str:
    """Resolve and ensure parent directory for the database path."""
    resolved_path = db_path or config.DATABASE_PATH
    path_obj = Path(resolved_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    return str(path_obj)


@contextmanager
def get_db_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Provide a thread-safe, WAL-enabled SQLite connection with row factories."""
    target_path = get_db_path(db_path)
    conn = sqlite3.connect(target_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        # Optimizations for Raspberry Pi Zero 2 W
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables and indexes, with migration for existing databases."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Main traffic samples table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS traffic_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                mac_address TEXT NOT NULL,
                bytes_rx INTEGER NOT NULL DEFAULT 0,
                bytes_tx INTEGER NOT NULL DEFAULT 0,
                download_bytes INTEGER NOT NULL DEFAULT 0,
                upload_bytes INTEGER NOT NULL DEFAULT 0,
                pkts_rx INTEGER NOT NULL DEFAULT 0,
                pkts_tx INTEGER NOT NULL DEFAULT 0,
                errors_rx INTEGER NOT NULL DEFAULT 0,
                errors_tx INTEGER NOT NULL DEFAULT 0,
                dropped_rx INTEGER NOT NULL DEFAULT 0,
                dropped_tx INTEGER NOT NULL DEFAULT 0
            );
        """)

        # Metadata table for devices (cached display name, IP, SSID, AP, etc.)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                mac_address TEXT PRIMARY KEY,
                hostname TEXT,
                ip_address TEXT,
                radio TEXT,
                ssid TEXT,
                ap TEXT,
                last_seen TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                first_seen TEXT,
                time_connected TEXT
            );
        """)

        # Migration: add first_seen and time_connected columns to existing databases
        _migrate_devices_table(cursor)

        # Performance indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_timestamp ON traffic_samples(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_mac ON traffic_samples(mac_address);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_timestamp_mac ON traffic_samples(timestamp, mac_address);")


def _migrate_devices_table(cursor: sqlite3.Cursor) -> None:
    """
    Safely add first_seen and time_connected columns to existing devices table.
    Idempotent: safe to run multiple times.
    """
    # Check existing columns
    cursor.execute("PRAGMA table_info(devices);")
    columns = {row["name"] for row in cursor.fetchall()}

    # Add first_seen column if missing
    if "first_seen" not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN first_seen TEXT;")
        # For existing devices, use earliest traffic_samples timestamp as first_seen
        # when available; otherwise fall back to last_seen.
        # This avoids fabricating historical data while using actual observed data.
        cursor.execute("""
            UPDATE devices
            SET first_seen = COALESCE((
                SELECT MIN(timestamp) FROM traffic_samples
                WHERE traffic_samples.mac_address = devices.mac_address
            ), last_seen)
            WHERE first_seen IS NULL;
        """)

    # Add time_connected column if missing
    if "time_connected" not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN time_connected TEXT;")
        # Existing rows keep NULL (no historical router data available)


def insert_sample(sample: Dict[str, Any], db_path: Optional[str] = None) -> int:
    """
    Insert a traffic sample into the database.
    Direction Semantics:
      download_bytes = delta of router current_tx
      upload_bytes   = delta of router current_rx
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO traffic_samples (
                timestamp, mac_address,
                bytes_rx, bytes_tx,
                download_bytes, upload_bytes,
                pkts_rx, pkts_tx,
                errors_rx, errors_tx,
                dropped_rx, dropped_tx
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sample["timestamp"],
            sample["mac_address"].upper(),
            sample.get("bytes_rx", 0),
            sample.get("bytes_tx", 0),
            sample.get("download_bytes", 0),
            sample.get("upload_bytes", 0),
            sample.get("pkts_rx", 0),
            sample.get("pkts_tx", 0),
            sample.get("errors_rx", 0),
            sample.get("errors_tx", 0),
            sample.get("dropped_rx", 0),
            sample.get("dropped_tx", 0),
        ))
        return cursor.lastrowid or 0


def upsert_device(device_info: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """Insert or update known device information."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO devices (mac_address, hostname, ip_address, radio, ssid, ap, last_seen, is_active, first_seen, time_connected)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mac_address) DO UPDATE SET
                hostname = COALESCE(excluded.hostname, devices.hostname),
                ip_address = COALESCE(excluded.ip_address, devices.ip_address),
                radio = COALESCE(excluded.radio, devices.radio),
                ssid = COALESCE(excluded.ssid, devices.ssid),
                ap = COALESCE(excluded.ap, devices.ap),
                last_seen = excluded.last_seen,
                is_active = excluded.is_active,
                first_seen = COALESCE(devices.first_seen, excluded.first_seen),
                time_connected = excluded.time_connected;
        """, (
            device_info["mac_address"].upper(),
            device_info.get("hostname"),
            device_info.get("ip_address"),
            device_info.get("radio"),
            device_info.get("ssid"),
            device_info.get("ap"),
            device_info.get("last_seen", datetime.now().isoformat()),
            1 if device_info.get("is_active", True) else 0,
            device_info.get("first_seen"),
            device_info.get("time_connected"),
        ))


def mark_devices_inactive_except(active_macs: List[str], db_path: Optional[str] = None) -> int:
    """
    Mark all known devices as inactive except those in the active_macs list.

    Used by the collector after a successful poll to update device activity state.
    Only call this on a FULLY SUCCESSFUL poll (no exceptions, no failed retries).

    Returns the number of devices whose is_active state changed to 0.
    """
    if not active_macs:
        # Empty list = all devices become inactive
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE devices SET is_active = 0 WHERE is_active = 1;")
            return cursor.rowcount

    # Use parameterized query with IN clause
    placeholders = ",".join("?" for _ in active_macs)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE devices SET is_active = 0 WHERE is_active = 1 AND mac_address NOT IN ({placeholders});",
            active_macs,
        )
        return cursor.rowcount


def get_latest_sample_for_mac(mac_address: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent traffic sample for a specific MAC address."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM traffic_samples
            WHERE mac_address = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1;
        """, (mac_address.upper(),))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_total_usage_between(start_iso: str, end_iso: str, db_path: Optional[str] = None) -> Dict[str, int]:
    """Calculate total download and upload bytes between two timestamps."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COALESCE(SUM(download_bytes), 0) as total_download,
                COALESCE(SUM(upload_bytes), 0) as total_upload
            FROM traffic_samples
            WHERE timestamp >= ? AND timestamp < ?;
        """, (start_iso, end_iso))
        row = cursor.fetchone()
        dl = row["total_download"] if row else 0
        ul = row["total_upload"] if row else 0
        return {
            "download_bytes": dl,
            "upload_bytes": ul,
            "total_bytes": dl + ul
        }


def get_network_stats_summary(db_path: Optional[str] = None) -> Dict[str, int]:
    """Get aggregated network-level counters and packet statistics."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COALESCE(SUM(bytes_rx), 0) as bytes_rx,
                COALESCE(SUM(bytes_tx), 0) as bytes_tx,
                COALESCE(SUM(pkts_rx), 0) as packets_rx,
                COALESCE(SUM(pkts_tx), 0) as packets_tx,
                COALESCE(SUM(errors_rx), 0) as errors_rx,
                COALESCE(SUM(errors_tx), 0) as errors_tx,
                COALESCE(SUM(dropped_rx), 0) as dropped_rx,
                COALESCE(SUM(dropped_tx), 0) as dropped_tx,
                COALESCE(SUM(download_bytes), 0) as download_bytes,
                COALESCE(SUM(upload_bytes), 0) as upload_bytes
            FROM traffic_samples;
        """)
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {
            "bytes_rx": 0, "bytes_tx": 0,
            "packets_rx": 0, "packets_tx": 0,
            "errors_rx": 0, "errors_tx": 0,
            "dropped_rx": 0, "dropped_tx": 0,
            "download_bytes": 0, "upload_bytes": 0
        }


# ==============================================================================
# RETENTION MANAGEMENT
# ==============================================================================
def purge_old_samples(retention_days: Optional[int] = None, db_path: Optional[str] = None) -> int:
    """
    Purge traffic samples older than retention_days.
    If retention_days <= 0 or not set, retention is disabled and 0 rows are deleted.
    """
    days = retention_days if retention_days is not None else config.DATA_RETENTION_DAYS
    if days <= 0:
        logger.debug("Retention pruning skipped: DATA_RETENTION_DAYS is 0 (retain indefinitely).")
        return 0

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM traffic_samples WHERE timestamp < ?;", (cutoff,))
        deleted_count = cursor.rowcount
        logger.info("Purged %d traffic samples older than %s (retention: %d days)", deleted_count, cutoff, days)
        return deleted_count


# ==============================================================================
# DATABASE INSPECTION UTILITIES
# ==============================================================================
def inspect_tables(db_path: Optional[str] = None) -> List[str]:
    """List all tables in the database."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        return [row["name"] for row in cursor.fetchall()]


def inspect_schema(db_path: Optional[str] = None) -> Dict[str, str]:
    """Return SQL DDL schemas for all tables and indexes."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name;")
        return {row["name"]: row["sql"] for row in cursor.fetchall()}


def inspect_latest_samples(limit: int = 5, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve the most recent traffic samples."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM traffic_samples ORDER BY timestamp DESC, id DESC LIMIT ?;", (limit,))
        return [dict(row) for row in cursor.fetchall()]


def inspect_device_count(db_path: Optional[str] = None) -> int:
    """Count total known devices."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM devices;")
        row = cursor.fetchone()
        return row["count"] if row else 0


def inspect_hourly_usage(date_prefix: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Inspect hourly usage breakdown for a given date (default today)."""
    prefix = date_prefix or datetime.now().strftime("%Y-%m-%d")
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                SUBSTR(timestamp, 12, 2) as hour,
                COALESCE(SUM(download_bytes), 0) as download_bytes,
                COALESCE(SUM(upload_bytes), 0) as upload_bytes,
                COALESCE(SUM(download_bytes + upload_bytes), 0) as total_bytes
            FROM traffic_samples
            WHERE timestamp LIKE ? || '%'
            GROUP BY SUBSTR(timestamp, 12, 2)
            ORDER BY hour ASC;
        """, (prefix,))
        return [dict(row) for row in cursor.fetchall()]


def inspect_daily_usage(limit_days: int = 7, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Inspect daily usage for the last N days."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                SUBSTR(timestamp, 1, 10) as day,
                COALESCE(SUM(download_bytes), 0) as download_bytes,
                COALESCE(SUM(upload_bytes), 0) as upload_bytes,
                COALESCE(SUM(download_bytes + upload_bytes), 0) as total_bytes
            FROM traffic_samples
            GROUP BY SUBSTR(timestamp, 1, 10)
            ORDER BY day DESC
            LIMIT ?;
        """, (limit_days,))
        return [dict(row) for row in cursor.fetchall()]


def inspect_device_history(mac_address: str, limit_days: int = 7, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Inspect daily history for a specific device."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                SUBSTR(timestamp, 1, 10) as day,
                COALESCE(SUM(download_bytes), 0) as download_bytes,
                COALESCE(SUM(upload_bytes), 0) as upload_bytes,
                COALESCE(SUM(download_bytes + upload_bytes), 0) as total_bytes
            FROM traffic_samples
            WHERE mac_address = ?
            GROUP BY SUBSTR(timestamp, 1, 10)
            ORDER BY day DESC
            LIMIT ?;
        """, (mac_address.upper(), limit_days))
        return [dict(row) for row in cursor.fetchall()]


# ==============================================================================
# CLI COMMAND DISPATCHER
# ==============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jio WiFi Data Tracker Database Utilities")
    parser.add_argument("--init", action="store_true", help="Initialize database tables and indexes")
    parser.add_argument("--tables", action="store_true", help="List database tables")
    parser.add_argument("--schema", action="store_true", help="Inspect database schema")
    parser.add_argument("--latest", type=int, nargs="?", const=5, help="Inspect latest N samples (default 5)")
    parser.add_argument("--devices", action="store_true", help="Inspect total registered devices")
    parser.add_argument("--hourly", action="store_true", help="Inspect today's hourly usage")
    parser.add_argument("--daily", type=int, nargs="?", const=7, help="Inspect last N daily usage (default 7)")
    parser.add_argument("--device-history", type=str, help="Inspect history for specific MAC address")
    parser.add_argument("--network-stats", action="store_true", help="Inspect network counters")
    parser.add_argument("--purge", type=int, help="Purge records older than N days")

    args = parser.parse_args()

    if args.init:
        init_db()
        print(f"Database initialized at {get_db_path()}")
    elif args.tables:
        print(json.dumps(inspect_tables(), indent=2))
    elif args.schema:
        print(json.dumps(inspect_schema(), indent=2))
    elif args.latest is not None:
        print(json.dumps(inspect_latest_samples(args.latest), indent=2))
    elif args.devices:
        print(f"Total devices: {inspect_device_count()}")
    elif args.hourly:
        print(json.dumps(inspect_hourly_usage(), indent=2))
    elif args.daily is not None:
        print(json.dumps(inspect_daily_usage(args.daily), indent=2))
    elif args.device_history:
        print(json.dumps(inspect_device_history(args.device_history), indent=2))
    elif args.network_stats:
        print(json.dumps(get_network_stats_summary(), indent=2))
    elif args.purge is not None:
        deleted = purge_old_samples(args.purge)
        print(f"Purged {deleted} records older than {args.purge} days.")
    else:
        parser.print_help()
