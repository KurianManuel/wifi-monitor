"""
Database layer for Jio WiFi Data Tracker.

Uses SQLite with WAL mode optimized for Raspberry Pi Zero 2 W.
Stores traffic samples and provides aggregated queries.

Direction Semantics:
- download_bytes = delta of router current_tx
- upload_bytes = delta of router current_rx
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from config import config


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
    """Initialize database tables and indexes."""
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
                is_active INTEGER NOT NULL DEFAULT 1
            );
        """)

        # Performance indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_timestamp ON traffic_samples(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_mac ON traffic_samples(mac_address);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_timestamp_mac ON traffic_samples(timestamp, mac_address);")


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
            INSERT INTO devices (mac_address, hostname, ip_address, radio, ssid, ap, last_seen, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mac_address) DO UPDATE SET
                hostname = COALESCE(excluded.hostname, devices.hostname),
                ip_address = COALESCE(excluded.ip_address, devices.ip_address),
                radio = COALESCE(excluded.radio, devices.radio),
                ssid = COALESCE(excluded.ssid, devices.ssid),
                ap = COALESCE(excluded.ap, devices.ap),
                last_seen = excluded.last_seen,
                is_active = excluded.is_active;
        """, (
            device_info["mac_address"].upper(),
            device_info.get("hostname"),
            device_info.get("ip_address"),
            device_info.get("radio"),
            device_info.get("ssid"),
            device_info.get("ap"),
            device_info.get("last_seen", datetime.now().isoformat()),
            1 if device_info.get("is_active", True) else 0,
        ))


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
