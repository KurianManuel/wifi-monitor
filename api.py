"""
Flask API Blueprint for Jio WiFi Data Tracker.

READ-ONLY API providing status, device data, traffic usage, and network statistics.
All endpoints return JSON and enforce no-store caching for live monitoring data.
Strictly respects Asia/Kolkata (IST) timezone.

Required endpoints:
- GET /api/status
- GET /api/devices
- GET /api/usage/today
- GET /api/usage/yesterday
- GET /api/usage/7days
- GET /api/usage/month
- GET /api/usage/daily
- GET /api/usage/hourly
- GET /api/devices/<mac>
- GET /api/devices/<mac>/daily
- GET /api/devices/<mac>/stats
- GET /api/network/stats
"""

import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    from datetime import timezone
    IST = timezone(timedelta(hours=5, minutes=30), name="IST")

from flask import Blueprint, Response, jsonify, request

import database
from config import config

logger = logging.getLogger("jio_wifi_tracker.api")
api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.after_request
def add_cache_headers(response: Response) -> Response:
    """Ensure all monitoring API responses are fresh and not cached."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def get_ist_now() -> datetime:
    """Return current datetime localized to Asia/Kolkata."""
    return datetime.now(IST)


def get_day_boundaries_ist(days_ago: int = 0) -> Tuple[datetime, datetime]:
    """Get start and end datetimes in IST for a day offset from today."""
    now_ist = get_ist_now()
    target_date = (now_ist - timedelta(days=days_ago)).date()
    start_of_day = datetime.combine(target_date, time.min, tzinfo=IST)
    end_of_day = start_of_day + timedelta(days=1)
    return start_of_day, end_of_day


# ------------------------------------------------------------------------------
# 1. GET /api/status
# ------------------------------------------------------------------------------
@api_bp.route("/status", methods=["GET"])
def get_status():
    now_ist = get_ist_now()
    return jsonify({
        "status": "online",
        "router": {
            "identity": "JioFiber Router" if config.is_mock else f"Jio Router ({config.ROUTER_HOST})",
            "host": config.ROUTER_HOST,
            "connected": True,
            "mode": config.MODE
        },
        "system": {
            "current_time_ist": now_ist.isoformat(),
            "timezone": config.TIMEZONE,
            "collection_interval": config.COLLECTION_INTERVAL,
            "dashboard_refresh_interval": config.DASHBOARD_REFRESH_INTERVAL
        }
    })


# ------------------------------------------------------------------------------
# 2. GET /api/devices
# ------------------------------------------------------------------------------
@api_bp.route("/devices", methods=["GET"])
def get_devices():
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
                    COALESCE(SUM(s.download_bytes), 0) as download_bytes,
                    COALESCE(SUM(s.upload_bytes), 0) as upload_bytes,
                    COALESCE(SUM(s.download_bytes + s.upload_bytes), 0) as total_bytes
                FROM devices d
                LEFT JOIN traffic_samples s ON d.mac_address = s.mac_address
                GROUP BY d.mac_address
                ORDER BY total_bytes DESC;
            """)
            devices = [dict(row) for row in cursor.fetchall()]
            return jsonify({
                "count": len(devices),
                "devices": devices
            })
    except Exception as e:
        logger.error("Error in /api/devices: %s", e)
        return jsonify({"error": "Failed to fetch devices", "devices": [], "count": 0}), 500


# ------------------------------------------------------------------------------
# 3. GET /api/usage/today
# ------------------------------------------------------------------------------
@api_bp.route("/usage/today", methods=["GET"])
def get_usage_today():
    start_ist, end_ist = get_day_boundaries_ist(0)
    usage = database.get_total_usage_between(start_ist.isoformat(), end_ist.isoformat())
    return jsonify({
        "period": "today",
        "start": start_ist.isoformat(),
        "end": end_ist.isoformat(),
        "download_bytes": usage["download_bytes"],
        "upload_bytes": usage["upload_bytes"],
        "total_bytes": usage["total_bytes"]
    })


# ------------------------------------------------------------------------------
# 4. GET /api/usage/yesterday
# ------------------------------------------------------------------------------
@api_bp.route("/usage/yesterday", methods=["GET"])
def get_usage_yesterday():
    start_ist, end_ist = get_day_boundaries_ist(1)
    usage = database.get_total_usage_between(start_ist.isoformat(), end_ist.isoformat())
    return jsonify({
        "period": "yesterday",
        "start": start_ist.isoformat(),
        "end": end_ist.isoformat(),
        "download_bytes": usage["download_bytes"],
        "upload_bytes": usage["upload_bytes"],
        "total_bytes": usage["total_bytes"]
    })


# ------------------------------------------------------------------------------
# 5. GET /api/usage/7days
# ------------------------------------------------------------------------------
@api_bp.route("/usage/7days", methods=["GET"])
def get_usage_7days():
    now_ist = get_ist_now()
    start_ist = datetime.combine((now_ist - timedelta(days=6)).date(), time.min, tzinfo=IST)
    end_ist = now_ist
    usage = database.get_total_usage_between(start_ist.isoformat(), end_ist.isoformat())
    return jsonify({
        "period": "7days",
        "start": start_ist.isoformat(),
        "end": end_ist.isoformat(),
        "download_bytes": usage["download_bytes"],
        "upload_bytes": usage["upload_bytes"],
        "total_bytes": usage["total_bytes"]
    })


# ------------------------------------------------------------------------------
# 6. GET /api/usage/month
# ------------------------------------------------------------------------------
@api_bp.route("/usage/month", methods=["GET"])
def get_usage_month():
    now_ist = get_ist_now()
    start_of_month = datetime(now_ist.year, now_ist.month, 1, 0, 0, 0, tzinfo=IST)
    usage = database.get_total_usage_between(start_of_month.isoformat(), now_ist.isoformat())
    return jsonify({
        "period": "month",
        "start": start_of_month.isoformat(),
        "end": now_ist.isoformat(),
        "download_bytes": usage["download_bytes"],
        "upload_bytes": usage["upload_bytes"],
        "total_bytes": usage["total_bytes"]
    })


# ------------------------------------------------------------------------------
# 7. GET /api/usage/daily
# ------------------------------------------------------------------------------
@api_bp.route("/usage/daily", methods=["GET"])
def get_usage_daily():
    """Get aggregated usage per day for the last 30 calendar days."""
    try:
        now_ist = get_ist_now()
        start_date = (now_ist - timedelta(days=30)).date()
        start_iso = datetime.combine(start_date, time.min, tzinfo=IST).isoformat()
        
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    SUBSTR(timestamp, 1, 10) as day,
                    COALESCE(SUM(download_bytes), 0) as download_bytes,
                    COALESCE(SUM(upload_bytes), 0) as upload_bytes,
                    COALESCE(SUM(download_bytes + upload_bytes), 0) as total_bytes
                FROM traffic_samples
                WHERE timestamp >= ?
                GROUP BY SUBSTR(timestamp, 1, 10)
                ORDER BY day ASC;
            """, (start_iso,))
            days = [dict(row) for row in cursor.fetchall()]
            return jsonify({
                "days": days
            })
    except Exception as e:
        logger.error("Error in /api/usage/daily: %s", e)
        return jsonify({"error": "Failed to fetch daily usage", "days": []}), 500


# ------------------------------------------------------------------------------
# 8. GET /api/usage/hourly
# ------------------------------------------------------------------------------
@api_bp.route("/usage/hourly", methods=["GET"])
def get_usage_hourly():
    """
    Returns full 24-hour timeline (00:00 through 23:00) for today (IST).
    Missing hours are padded with 0 values so the chart never breaks.
    """
    try:
        start_ist, end_ist = get_day_boundaries_ist(0)
        start_iso = start_ist.isoformat()
        end_iso = end_ist.isoformat()

        # Query database for available hourly buckets today
        hourly_data: Dict[str, Dict[str, int]] = {}
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    SUBSTR(timestamp, 12, 2) as hour,
                    COALESCE(SUM(download_bytes), 0) as download_bytes,
                    COALESCE(SUM(upload_bytes), 0) as upload_bytes
                FROM traffic_samples
                WHERE timestamp >= ? AND timestamp < ?
                GROUP BY SUBSTR(timestamp, 12, 2);
            """, (start_iso, end_iso))
            for row in cursor.fetchall():
                hour_key = f"{int(row['hour']):02d}:00"
                hourly_data[hour_key] = {
                    "download_bytes": row["download_bytes"],
                    "upload_bytes": row["upload_bytes"],
                    "total_bytes": row["download_bytes"] + row["upload_bytes"]
                }

        # Ensure complete 24 hours 00:00 to 23:00
        full_24h = []
        for h in range(24):
            hour_label = f"{h:02d}:00"
            if hour_label in hourly_data:
                data = hourly_data[hour_label]
            else:
                data = {"download_bytes": 0, "upload_bytes": 0, "total_bytes": 0}
            full_24h.append({
                "hour": hour_label,
                "download_bytes": data["download_bytes"],
                "upload_bytes": data["upload_bytes"],
                "total_bytes": data["total_bytes"]
            })

        return jsonify({
            "date": start_ist.strftime("%Y-%m-%d"),
            "timezone": "Asia/Kolkata",
            "hours": full_24h
        })
    except Exception as e:
        logger.error("Error in /api/usage/hourly: %s", e)
        return jsonify({"error": "Failed to fetch hourly usage", "hours": []}), 500


# ------------------------------------------------------------------------------
# 9. GET /api/devices/<mac>
# ------------------------------------------------------------------------------
@api_bp.route("/devices/<mac>", methods=["GET"])
def get_device_details(mac: str):
    clean_mac = mac.upper()
    try:
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM devices WHERE mac_address = ?;", (clean_mac,))
            device = cursor.fetchone()
            if not device:
                return jsonify({"error": "Device not found", "mac_address": clean_mac}), 404
            
            # Aggregate total usage
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(download_bytes), 0) as total_download,
                    COALESCE(SUM(upload_bytes), 0) as total_upload
                FROM traffic_samples
                WHERE mac_address = ?;
            """, (clean_mac,))
            usage = cursor.fetchone()
            dl = usage["total_download"] if usage else 0
            ul = usage["total_upload"] if usage else 0
            
            res = dict(device)
            res["download_bytes"] = dl
            res["upload_bytes"] = ul
            res["total_bytes"] = dl + ul
            return jsonify(res)
    except Exception as e:
        logger.error("Error in /api/devices/%s: %s", clean_mac, e)
        return jsonify({"error": "Internal server error"}), 500


# ------------------------------------------------------------------------------
# 10. GET /api/devices/<mac>/daily
# ------------------------------------------------------------------------------
@api_bp.route("/devices/<mac>/daily", methods=["GET"])
def get_device_daily(mac: str):
    """Last 7 calendar days usage for this device, padded for missing days."""
    clean_mac = mac.upper()
    try:
        now_ist = get_ist_now()
        start_date = (now_ist - timedelta(days=6)).date()
        start_iso = datetime.combine(start_date, time.min, tzinfo=IST).isoformat()
        
        days_map: Dict[str, Dict[str, int]] = {}
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    SUBSTR(timestamp, 1, 10) as day,
                    COALESCE(SUM(download_bytes), 0) as download_bytes,
                    COALESCE(SUM(upload_bytes), 0) as upload_bytes
                FROM traffic_samples
                WHERE mac_address = ? AND timestamp >= ?
                GROUP BY SUBSTR(timestamp, 1, 10)
                ORDER BY day ASC;
            """, (clean_mac, start_iso))
            for row in cursor.fetchall():
                days_map[row["day"]] = {
                    "download_bytes": row["download_bytes"],
                    "upload_bytes": row["upload_bytes"],
                    "total_bytes": row["download_bytes"] + row["upload_bytes"]
                }

        # Pad 7 days
        padded = []
        for i in range(6, -1, -1):
            d_str = (now_ist - timedelta(days=i)).strftime("%Y-%m-%d")
            entry = days_map.get(d_str, {"download_bytes": 0, "upload_bytes": 0, "total_bytes": 0})
            padded.append({
                "day": d_str,
                "download_bytes": entry["download_bytes"],
                "upload_bytes": entry["upload_bytes"],
                "total_bytes": entry["total_bytes"]
            })

        return jsonify({
            "mac_address": clean_mac,
            "days": padded
        })
    except Exception as e:
        logger.error("Error in /api/devices/%s/daily: %s", clean_mac, e)
        return jsonify({"error": "Failed to fetch device daily usage", "days": []}), 500


# ------------------------------------------------------------------------------
# 11. GET /api/devices/<mac>/stats
# ------------------------------------------------------------------------------
@api_bp.route("/devices/<mac>/stats", methods=["GET"])
def get_device_stats(mac: str):
    """Detailed cumulative network stats for a device."""
    clean_mac = mac.upper()
    try:
        with database.get_db_connection() as conn:
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
                FROM traffic_samples
                WHERE mac_address = ?;
            """, (clean_mac,))
            row = cursor.fetchone()
            stats = dict(row) if row else {}
            stats["mac_address"] = clean_mac
            return jsonify(stats)
    except Exception as e:
        logger.error("Error in /api/devices/%s/stats: %s", clean_mac, e)
        return jsonify({"error": "Failed to fetch device stats"}), 500


# ------------------------------------------------------------------------------
# 12. GET /api/network/stats
# ------------------------------------------------------------------------------
@api_bp.route("/network/stats", methods=["GET"])
def get_network_stats():
    """Network-level counters, packet statistics, errors, and drops."""
    try:
        stats = database.get_network_stats_summary()
        return jsonify(stats)
    except Exception as e:
        logger.error("Error in /api/network/stats: %s", e)
        return jsonify({"error": "Failed to fetch network statistics"}), 500
