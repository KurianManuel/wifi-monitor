"""
Flask API Blueprint for Jio WiFi Data Tracker.

READ-ONLY API providing status, device data, traffic usage, and network statistics.
All endpoints return JSON and enforce no-store caching for live monitoring data.
Strictly respects Asia/Kolkata (IST) timezone throughout.

CRITICAL: Traffic direction semantics are locked and must not be reversed anywhere:
  download_bytes = delta(router bytesTx)   — device transmitted
  upload_bytes   = delta(router bytesRx)   — device received

Required endpoints:
  GET /api/status
  GET /api/devices
  GET /api/usage/today
  GET /api/usage/yesterday
  GET /api/usage/7days
  GET /api/usage/month
  GET /api/usage/daily
  GET /api/usage/hourly
  GET /api/devices/<mac>
  GET /api/devices/<mac>/daily
  GET /api/devices/<mac>/stats
  GET /api/network/stats
"""

import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    _IST = ZoneInfo("Asia/Kolkata")
except Exception:
    from datetime import timezone
    _IST = timezone(timedelta(hours=5, minutes=30), name="IST")

from flask import Blueprint, Response, jsonify

import database
from config import config

logger = logging.getLogger("jio_wifi_tracker.api")
api_bp = Blueprint("api", __name__, url_prefix="/api")

# ---------------------------------------------------------------------------
# MAC address validation
# ---------------------------------------------------------------------------
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")


def _is_valid_mac(mac: str) -> bool:
    return bool(_MAC_RE.match(mac))


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
@api_bp.after_request
def add_cache_headers(response: Response) -> Response:
    """Ensure all monitoring API responses are fresh and not cached by proxies."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ---------------------------------------------------------------------------
# IST Helpers
# ---------------------------------------------------------------------------

def _ist_now() -> datetime:
    """Return current datetime in Asia/Kolkata (IST)."""
    return datetime.now(_IST)


def _ist_naive_now() -> datetime:
    """
    Return current naive datetime that represents IST wall-clock time.
    Matches the format produced by datetime.now().isoformat() on a Pi in IST.
    Used to build DB comparison strings that match collector-stored timestamps.
    """
    aware = _ist_now()
    return aware.replace(tzinfo=None)


def _day_naive_boundaries(days_ago: int = 0) -> Tuple[str, str]:
    """
    Return (start_iso, end_iso) as naive IST ISO strings for DB range queries.

    The collector stores timestamps as datetime.now().isoformat() (naive, local IST).
    We must compare against the same naive-IST format for correct day boundaries.

    Returns:
        start_iso: "YYYY-MM-DDTHH:MM:SS" — midnight IST of target day
        end_iso:   "YYYY-MM-DDTHH:MM:SS" — midnight IST of next day (exclusive)
    """
    today_ist = _ist_naive_now().date()
    target_date = today_ist - timedelta(days=days_ago)
    start_dt = datetime.combine(target_date, time.min)      # 00:00:00 IST naive
    end_dt = start_dt + timedelta(days=1)                   # 00:00:00 IST naive + 1 day
    return start_dt.isoformat(), end_dt.isoformat()


def _month_naive_boundaries() -> Tuple[str, str]:
    """Return (start_iso, end_iso) for the current IST calendar month."""
    now_ist = _ist_naive_now()
    start_of_month = datetime(now_ist.year, now_ist.month, 1, 0, 0, 0)
    # End should be end of current IST day (midnight next day), not current time
    end_of_today = _day_naive_boundaries(0)[1]
    return start_of_month.isoformat(), end_of_today


def _n_days_naive_start(n: int) -> str:
    """Return naive IST ISO string for midnight n-1 days ago (for last-N-days window)."""
    today_ist = _ist_naive_now().date()
    start_date = today_ist - timedelta(days=n - 1)
    return datetime.combine(start_date, time.min).isoformat()


# ---------------------------------------------------------------------------
# 1. GET /api/status
# ---------------------------------------------------------------------------
@api_bp.route("/status", methods=["GET"])
def get_status():
    """
    Return current router/application status.
    Never exposes credentials, passwords, or authentication tokens.
    """
    try:
        now_ist = _ist_now()

        # Pull lightweight stats from database
        try:
            device_count = database.inspect_device_count()
            latest_samples = database.inspect_latest_samples(limit=1)
            last_sample_time = latest_samples[0]["timestamp"] if latest_samples else None
        except Exception:
            device_count = 0
            last_sample_time = None

        return jsonify({
            "status": "online",
            "router": {
                "host": config.ROUTER_HOST,
                "mode": config.MODE,
                "identity": (
                    "JioFiber/JioAirFiber Router (Mock)"
                    if config.is_mock
                    else f"JioFiber/JioAirFiber Router ({config.ROUTER_HOST})"
                ),
            },
            "collector": {
                "mode": config.MODE,
                "collection_interval_seconds": config.COLLECTION_INTERVAL,
                "last_sample_time": last_sample_time,
            },
            "devices": {
                "known_count": device_count,
            },
            "system": {
                "current_time_ist": now_ist.isoformat(),
                "timezone": "Asia/Kolkata",
                "dashboard_refresh_interval_seconds": config.DASHBOARD_REFRESH_INTERVAL,
            },
        })
    except Exception as e:
        logger.error("Error in /api/status: %s", e)
        return jsonify({"error": "Failed to retrieve status"}), 500


# ---------------------------------------------------------------------------
# 2. GET /api/devices
# ---------------------------------------------------------------------------
@api_bp.route("/devices", methods=["GET"])
def get_devices():
    """
    Return all known devices with their all-time cumulative traffic totals.
    MAC addresses are normalized to uppercase with colons.
    """
    try:
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    d.mac_address,
                    d.hostname,
                    d.ip_address,
                    d.radio,
                    d.ssid,
                    d.ap,
                    d.last_seen,
                    d.is_active,
                    COALESCE(SUM(s.download_bytes), 0)             AS download_bytes,
                    COALESCE(SUM(s.upload_bytes), 0)               AS upload_bytes,
                    COALESCE(SUM(s.download_bytes + s.upload_bytes), 0) AS total_bytes
                FROM devices d
                LEFT JOIN traffic_samples s ON d.mac_address = s.mac_address
                GROUP BY d.mac_address
                ORDER BY total_bytes DESC;
            """)
            devices = [dict(row) for row in cursor.fetchall()]

        return jsonify({
            "count": len(devices),
            "devices": devices,
        })
    except Exception as e:
        logger.error("Error in /api/devices: %s", e)
        return jsonify({"error": "Failed to fetch devices", "devices": [], "count": 0}), 500


# ---------------------------------------------------------------------------
# 3. GET /api/usage/today
# ---------------------------------------------------------------------------
@api_bp.route("/usage/today", methods=["GET"])
def get_usage_today():
    """Total download/upload/combined traffic for today (IST calendar day)."""
    try:
        start_iso, end_iso = _day_naive_boundaries(0)
        usage = database.get_total_usage_between(start_iso, end_iso)
        return jsonify({
            "period": "today",
            "start": start_iso,
            "end": end_iso,
            "download_bytes": usage["download_bytes"],
            "upload_bytes": usage["upload_bytes"],
            "total_bytes": usage["total_bytes"],
        })
    except Exception as e:
        logger.error("Error in /api/usage/today: %s", e)
        return jsonify({"error": "Failed to fetch today's usage"}), 500


# ---------------------------------------------------------------------------
# 4. GET /api/usage/yesterday
# ---------------------------------------------------------------------------
@api_bp.route("/usage/yesterday", methods=["GET"])
def get_usage_yesterday():
    """Total download/upload/combined traffic for yesterday (IST calendar day)."""
    try:
        start_iso, end_iso = _day_naive_boundaries(1)
        usage = database.get_total_usage_between(start_iso, end_iso)
        return jsonify({
            "period": "yesterday",
            "start": start_iso,
            "end": end_iso,
            "download_bytes": usage["download_bytes"],
            "upload_bytes": usage["upload_bytes"],
            "total_bytes": usage["total_bytes"],
        })
    except Exception as e:
        logger.error("Error in /api/usage/yesterday: %s", e)
        return jsonify({"error": "Failed to fetch yesterday's usage"}), 500


# ---------------------------------------------------------------------------
# 5. GET /api/usage/7days
# ---------------------------------------------------------------------------
@api_bp.route("/usage/7days", methods=["GET"])
def get_usage_7days():
    """Total download/upload/combined traffic for the last 7 calendar days (IST)."""
    try:
        start_iso = _n_days_naive_start(7)
        # Use end of current IST day (midnight tomorrow) for deterministic calendar-day boundary
        end_iso = _day_naive_boundaries(0)[1]
        usage = database.get_total_usage_between(start_iso, end_iso)
        return jsonify({
            "period": "7days",
            "start": start_iso,
            "end": end_iso,
            "download_bytes": usage["download_bytes"],
            "upload_bytes": usage["upload_bytes"],
            "total_bytes": usage["total_bytes"],
        })
    except Exception as e:
        logger.error("Error in /api/usage/7days: %s", e)
        return jsonify({"error": "Failed to fetch 7-day usage"}), 500


# ---------------------------------------------------------------------------
# 6. GET /api/usage/month
# ---------------------------------------------------------------------------
@api_bp.route("/usage/month", methods=["GET"])
def get_usage_month():
    """Total download/upload/combined traffic since the 1st of the current IST month."""
    try:
        start_iso, end_iso = _month_naive_boundaries()
        usage = database.get_total_usage_between(start_iso, end_iso)
        return jsonify({
            "period": "month",
            "start": start_iso,
            "end": end_iso,
            "download_bytes": usage["download_bytes"],
            "upload_bytes": usage["upload_bytes"],
            "total_bytes": usage["total_bytes"],
        })
    except Exception as e:
        logger.error("Error in /api/usage/month: %s", e)
        return jsonify({"error": "Failed to fetch monthly usage"}), 500


# ---------------------------------------------------------------------------
# 7. GET /api/usage/daily
# ---------------------------------------------------------------------------
@api_bp.route("/usage/daily", methods=["GET"])
def get_usage_daily():
    """
    Aggregate network-wide usage per calendar day (IST) for the last 30 days.
    Returns list of {date, download_bytes, upload_bytes, total_bytes}.
    Missing days (no data) are omitted; frontend can pad if needed.
    """
    try:
        start_iso = _n_days_naive_start(30)

        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            # SUBSTR(timestamp, 1, 10) extracts "YYYY-MM-DD" from naive IST ISO strings
            cursor.execute("""
                SELECT
                    SUBSTR(timestamp, 1, 10)                            AS date,
                    COALESCE(SUM(download_bytes), 0)                    AS download_bytes,
                    COALESCE(SUM(upload_bytes), 0)                      AS upload_bytes,
                    COALESCE(SUM(download_bytes + upload_bytes), 0)     AS total_bytes
                FROM traffic_samples
                WHERE timestamp >= ?
                GROUP BY SUBSTR(timestamp, 1, 10)
                ORDER BY date ASC;
            """, (start_iso,))
            days = [dict(row) for row in cursor.fetchall()]

        return jsonify({"days": days})
    except Exception as e:
        logger.error("Error in /api/usage/daily: %s", e)
        return jsonify({"error": "Failed to fetch daily usage", "days": []}), 500


# ---------------------------------------------------------------------------
# 8. GET /api/usage/hourly
# ---------------------------------------------------------------------------
@api_bp.route("/usage/hourly", methods=["GET"])
def get_usage_hourly():
    """
    Return full 24-hour timeline (00:00 through 23:00) for the current IST calendar day.

    - Queries all samples whose timestamp falls within today's IST day boundaries.
    - Missing hours are filled with zero values so the chart always has 24 entries.
    - Historical hours (e.g. 20:00, 21:00, 22:00 from earlier in the day) are always
      included — they do not disappear around midnight.
    """
    try:
        start_iso, end_iso = _day_naive_boundaries(0)
        today_date = _ist_naive_now().date().isoformat()

        # Build a lookup of hour → {download, upload} from stored samples
        hourly_lookup: Dict[str, Dict[str, int]] = {}
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            # SUBSTR(timestamp, 12, 2) extracts the HH from "YYYY-MM-DDTHH:MM:SS..."
            cursor.execute("""
                SELECT
                    SUBSTR(timestamp, 12, 2)                    AS hour_str,
                    COALESCE(SUM(download_bytes), 0)            AS download_bytes,
                    COALESCE(SUM(upload_bytes), 0)              AS upload_bytes
                FROM traffic_samples
                WHERE timestamp >= ? AND timestamp < ?
                GROUP BY SUBSTR(timestamp, 12, 2);
            """, (start_iso, end_iso))
            for row in cursor.fetchall():
                # hour_str is "HH" from the 12th character of the ISO string
                h = row["hour_str"]
                try:
                    hour_label = f"{int(h):02d}:00"
                except (ValueError, TypeError):
                    continue
                hourly_lookup[hour_label] = {
                    "download_bytes": row["download_bytes"],
                    "upload_bytes": row["upload_bytes"],
                    "total_bytes": row["download_bytes"] + row["upload_bytes"],
                }

        # Produce full 24-entry list — always complete, zero-padded
        hours = []
        for h in range(24):
            label = f"{h:02d}:00"
            entry = hourly_lookup.get(label, {"download_bytes": 0, "upload_bytes": 0, "total_bytes": 0})
            hours.append({
                "hour": label,
                "download_bytes": entry["download_bytes"],
                "upload_bytes": entry["upload_bytes"],
                "total_bytes": entry["total_bytes"],
            })

        return jsonify({
            "date": today_date,
            "timezone": "Asia/Kolkata",
            "hours": hours,
        })
    except Exception as e:
        logger.error("Error in /api/usage/hourly: %s", e)
        return jsonify({"error": "Failed to fetch hourly usage", "hours": []}), 500


# ---------------------------------------------------------------------------
# 9. GET /api/devices/<mac>
# ---------------------------------------------------------------------------
@api_bp.route("/devices/<mac>", methods=["GET"])
def get_device_details(mac: str):
    """
    Return full device identity plus usage breakdowns:
      - today, yesterday, last 7 days, this month
      - all-time totals

    Returns 400 for malformed MAC, 404 if device not found.
    """
    clean_mac = mac.strip().upper()

    if not _is_valid_mac(clean_mac):
        return jsonify({
            "error": "Invalid MAC address format",
            "mac_address": clean_mac,
        }), 400

    try:
        with database.get_db_connection() as conn:
            cursor = conn.cursor()

            # Device identity
            cursor.execute("SELECT * FROM devices WHERE mac_address = ?;", (clean_mac,))
            device_row = cursor.fetchone()
            if device_row is None:
                return jsonify({"error": "Device not found", "mac_address": clean_mac}), 404

            device = dict(device_row)

            # All-time totals
            cursor.execute("""
                SELECT
                    COALESCE(SUM(download_bytes), 0) AS download_bytes,
                    COALESCE(SUM(upload_bytes), 0)   AS upload_bytes
                FROM traffic_samples
                WHERE mac_address = ?;
            """, (clean_mac,))
            all_time = cursor.fetchone()
            dl_all = all_time["download_bytes"] if all_time else 0
            ul_all = all_time["upload_bytes"] if all_time else 0

            # Today
            t_start, t_end = _day_naive_boundaries(0)
            cursor.execute("""
                SELECT COALESCE(SUM(download_bytes), 0) AS dl,
                       COALESCE(SUM(upload_bytes), 0)   AS ul
                FROM traffic_samples
                WHERE mac_address = ? AND timestamp >= ? AND timestamp < ?;
            """, (clean_mac, t_start, t_end))
            r = cursor.fetchone()
            today_dl, today_ul = (r["dl"], r["ul"]) if r else (0, 0)

            # Yesterday
            y_start, y_end = _day_naive_boundaries(1)
            cursor.execute("""
                SELECT COALESCE(SUM(download_bytes), 0) AS dl,
                       COALESCE(SUM(upload_bytes), 0)   AS ul
                FROM traffic_samples
                WHERE mac_address = ? AND timestamp >= ? AND timestamp < ?;
            """, (clean_mac, y_start, y_end))
            r = cursor.fetchone()
            yday_dl, yday_ul = (r["dl"], r["ul"]) if r else (0, 0)

            # Last 7 days
            s7_start = _n_days_naive_start(7)
            s7_end = _ist_naive_now().isoformat()
            cursor.execute("""
                SELECT COALESCE(SUM(download_bytes), 0) AS dl,
                       COALESCE(SUM(upload_bytes), 0)   AS ul
                FROM traffic_samples
                WHERE mac_address = ? AND timestamp >= ? AND timestamp < ?;
            """, (clean_mac, s7_start, s7_end))
            r = cursor.fetchone()
            w7_dl, w7_ul = (r["dl"], r["ul"]) if r else (0, 0)

            # This month
            m_start, m_end = _month_naive_boundaries()
            cursor.execute("""
                SELECT COALESCE(SUM(download_bytes), 0) AS dl,
                       COALESCE(SUM(upload_bytes), 0)   AS ul
                FROM traffic_samples
                WHERE mac_address = ? AND timestamp >= ? AND timestamp < ?;
            """, (clean_mac, m_start, m_end))
            r = cursor.fetchone()
            mon_dl, mon_ul = (r["dl"], r["ul"]) if r else (0, 0)

        return jsonify({
            "mac_address": device["mac_address"],
            "hostname": device.get("hostname"),
            "ip_address": device.get("ip_address"),
            "radio": device.get("radio"),
            "ssid": device.get("ssid"),
            "ap": device.get("ap"),
            "last_seen": device.get("last_seen"),
            "first_seen": device.get("first_seen"),
            "time_connected": device.get("time_connected"),
            "is_active": bool(device.get("is_active", 1)),
            "usage": {
                "all_time": {
                    "download_bytes": dl_all,
                    "upload_bytes": ul_all,
                    "total_bytes": dl_all + ul_all,
                },
                "today": {
                    "download_bytes": today_dl,
                    "upload_bytes": today_ul,
                    "total_bytes": today_dl + today_ul,
                },
                "yesterday": {
                    "download_bytes": yday_dl,
                    "upload_bytes": yday_ul,
                    "total_bytes": yday_dl + yday_ul,
                },
                "last_7_days": {
                    "download_bytes": w7_dl,
                    "upload_bytes": w7_ul,
                    "total_bytes": w7_dl + w7_ul,
                },
                "this_month": {
                    "download_bytes": mon_dl,
                    "upload_bytes": mon_ul,
                    "total_bytes": mon_dl + mon_ul,
                },
            },
        })
    except Exception as e:
        logger.error("Error in /api/devices/%s: %s", clean_mac, e)
        return jsonify({"error": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# 10. GET /api/devices/<mac>/daily
# ---------------------------------------------------------------------------
@api_bp.route("/devices/<mac>/daily", methods=["GET"])
def get_device_daily(mac: str):
    """
    Return last 7 calendar days usage for a specific device (IST), zero-padded.
    Each day entry: {date, download_bytes, upload_bytes, total_bytes}.
    """
    clean_mac = mac.strip().upper()

    if not _is_valid_mac(clean_mac):
        return jsonify({
            "error": "Invalid MAC address format",
            "mac_address": clean_mac,
        }), 400

    try:
        start_iso = _n_days_naive_start(7)

        days_map: Dict[str, Dict[str, int]] = {}
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    SUBSTR(timestamp, 1, 10)                            AS date,
                    COALESCE(SUM(download_bytes), 0)                    AS download_bytes,
                    COALESCE(SUM(upload_bytes), 0)                      AS upload_bytes,
                    COALESCE(SUM(download_bytes + upload_bytes), 0)     AS total_bytes
                FROM traffic_samples
                WHERE mac_address = ? AND timestamp >= ?
                GROUP BY SUBSTR(timestamp, 1, 10)
                ORDER BY date ASC;
            """, (clean_mac, start_iso))
            for row in cursor.fetchall():
                days_map[row["date"]] = {
                    "download_bytes": row["download_bytes"],
                    "upload_bytes": row["upload_bytes"],
                    "total_bytes": row["total_bytes"],
                }

        # Zero-pad all 7 days including days with no data
        today_ist = _ist_naive_now().date()
        padded = []
        for i in range(6, -1, -1):
            d_str = (today_ist - timedelta(days=i)).isoformat()
            entry = days_map.get(d_str, {"download_bytes": 0, "upload_bytes": 0, "total_bytes": 0})
            padded.append({
                "date": d_str,
                "download_bytes": entry["download_bytes"],
                "upload_bytes": entry["upload_bytes"],
                "total_bytes": entry["total_bytes"],
            })

        return jsonify({
            "mac_address": clean_mac,
            "days": padded,
        })
    except Exception as e:
        logger.error("Error in /api/devices/%s/daily: %s", clean_mac, e)
        return jsonify({"error": "Failed to fetch device daily usage", "days": []}), 500


# ---------------------------------------------------------------------------
# 11. GET /api/devices/<mac>/stats
# ---------------------------------------------------------------------------
@api_bp.route("/devices/<mac>/stats", methods=["GET"])
def get_device_stats(mac: str):
    """
    Return cumulative network-level counters for a specific device.
    Fields: bytes_rx, bytes_tx, packets_rx, packets_tx,
            errors_rx, errors_tx, dropped_rx, dropped_tx,
            download_bytes, upload_bytes, total_bytes.
    Returns 400 for invalid MAC. Returns zeroed stats if device has no samples.
    """
    clean_mac = mac.strip().upper()

    if not _is_valid_mac(clean_mac):
        return jsonify({
            "error": "Invalid MAC address format",
            "mac_address": clean_mac,
        }), 400

    try:
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COALESCE(SUM(bytes_rx), 0)      AS bytes_rx,
                    COALESCE(SUM(bytes_tx), 0)      AS bytes_tx,
                    COALESCE(SUM(pkts_rx), 0)       AS packets_rx,
                    COALESCE(SUM(pkts_tx), 0)       AS packets_tx,
                    COALESCE(SUM(errors_rx), 0)     AS errors_rx,
                    COALESCE(SUM(errors_tx), 0)     AS errors_tx,
                    COALESCE(SUM(dropped_rx), 0)    AS dropped_rx,
                    COALESCE(SUM(dropped_tx), 0)    AS dropped_tx,
                    COALESCE(SUM(download_bytes), 0) AS download_bytes,
                    COALESCE(SUM(upload_bytes), 0)  AS upload_bytes
                FROM traffic_samples
                WHERE mac_address = ?;
            """, (clean_mac,))
            row = cursor.fetchone()

        stats: Dict[str, Any] = dict(row) if row else {}
        stats["mac_address"] = clean_mac
        dl = stats.get("download_bytes", 0)
        ul = stats.get("upload_bytes", 0)
        stats["total_bytes"] = dl + ul
        return jsonify(stats)
    except Exception as e:
        logger.error("Error in /api/devices/%s/stats: %s", clean_mac, e)
        return jsonify({"error": "Failed to fetch device stats"}), 500


# ---------------------------------------------------------------------------
# 12. GET /api/network/stats
# ---------------------------------------------------------------------------
@api_bp.route("/network/stats", methods=["GET"])
def get_network_stats():
    """
    Return network-wide aggregated counters across all devices and all time.
    Fields: bytes_rx, bytes_tx, packets_rx, packets_tx,
            errors_rx, errors_tx, dropped_rx, dropped_tx,
            download_bytes, upload_bytes.
    Never fabricates values — returns actual database aggregates.
    """
    try:
        stats = database.get_network_stats_summary()
        return jsonify(stats)
    except Exception as e:
        logger.error("Error in /api/network/stats: %s", e)
        return jsonify({"error": "Failed to fetch network statistics"}), 500
