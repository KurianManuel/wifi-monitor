"""
API Regression and Functional Tests for Jio WiFi Data Tracker.

Tests ALL 12 required endpoints:
  1.  GET /api/status
  2.  GET /api/devices
  3.  GET /api/usage/today
  4.  GET /api/usage/yesterday
  5.  GET /api/usage/7days
  6.  GET /api/usage/month
  7.  GET /api/usage/daily
  8.  GET /api/usage/hourly
  9.  GET /api/devices/<mac>
  10. GET /api/devices/<mac>/daily
  11. GET /api/devices/<mac>/stats
  12. GET /api/network/stats

Also covers:
  - Empty database
  - Missing device (404)
  - Invalid MAC format (400)
  - no-store cache headers
  - Correct download/upload direction semantics (no reversal)
  - 24-hour complete hourly response (always 24 entries)
  - IST day boundary correctness
  - Per-period device usage breakdowns (today/yesterday/7days/month)
  - Network stats fields
  - Device stats fields
"""

import os
import tempfile
from datetime import datetime, timedelta

import pytest

import database
from app import create_app


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def client(tmp_path):
    """
    Flask test client with a fully isolated temporary SQLite database.
    Patches config.DATABASE_PATH so all DB calls use the test DB.
    """
    db_path = str(tmp_path / "test_traffic.db")
    database.init_db(db_path)

    import config as cfg_module
    original_db = cfg_module.config.DATABASE_PATH
    object.__setattr__(cfg_module.config, "DATABASE_PATH", db_path)

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as test_client:
        yield test_client

    object.__setattr__(cfg_module.config, "DATABASE_PATH", original_db)


@pytest.fixture
def seeded_client(tmp_path):
    """
    Flask test client with pre-seeded device and traffic data.
    Inserts samples spread across today, yesterday, and 7 days ago.
    Uses naive IST timestamp strings matching the collector format.
    """
    db_path = str(tmp_path / "seeded_traffic.db")
    database.init_db(db_path)

    import config as cfg_module
    original_db = cfg_module.config.DATABASE_PATH
    object.__setattr__(cfg_module.config, "DATABASE_PATH", db_path)

    # Determine IST-naive today
    try:
        from zoneinfo import ZoneInfo
        ist = ZoneInfo("Asia/Kolkata")
        from datetime import timezone as _tz
        now_ist_naive = datetime.now(ist).replace(tzinfo=None)
    except Exception:
        now_ist_naive = datetime.now()

    today_str = now_ist_naive.strftime("%Y-%m-%d")
    yesterday_str = (now_ist_naive - timedelta(days=1)).strftime("%Y-%m-%d")
    seven_days_str = (now_ist_naive - timedelta(days=6)).strftime("%Y-%m-%d")

    MAC_A = "AA:BB:CC:11:22:33"
    MAC_B = "DD:EE:FF:44:55:66"

    # Device A — present today, yesterday, and 7 days ago
    database.upsert_device({
        "mac_address": MAC_A,
        "hostname": "Laptop-Alpha",
        "ip_address": "192.168.29.10",
        "radio": "5GHz",
        "ssid": "JioFiber-5G",
        "ap": "AP1",
        "last_seen": f"{today_str}T10:00:00",
        "is_active": True,
    }, db_path)

    # Device B — only today
    database.upsert_device({
        "mac_address": MAC_B,
        "hostname": "Phone-Beta",
        "ip_address": "192.168.29.11",
        "radio": "2.4GHz",
        "ssid": "JioFiber-2G",
        "ap": "AP1",
        "last_seen": f"{today_str}T11:00:00",
        "is_active": True,
    }, db_path)

    # Samples: today — A downloads 1000, uploads 400
    database.insert_sample({
        "timestamp": f"{today_str}T08:00:00",
        "mac_address": MAC_A,
        "bytes_rx": 5000,
        "bytes_tx": 10000,
        "download_bytes": 600,
        "upload_bytes": 200,
        "pkts_rx": 50,
        "pkts_tx": 100,
        "errors_rx": 1,
        "errors_tx": 0,
        "dropped_rx": 0,
        "dropped_tx": 0,
    }, db_path)
    database.insert_sample({
        "timestamp": f"{today_str}T09:00:00",
        "mac_address": MAC_A,
        "bytes_rx": 5400,
        "bytes_tx": 11000,
        "download_bytes": 400,
        "upload_bytes": 200,
        "pkts_rx": 40,
        "pkts_tx": 90,
        "errors_rx": 0,
        "errors_tx": 1,
        "dropped_rx": 0,
        "dropped_tx": 0,
    }, db_path)

    # Today — B downloads 800, uploads 300
    database.insert_sample({
        "timestamp": f"{today_str}T10:00:00",
        "mac_address": MAC_B,
        "bytes_rx": 3000,
        "bytes_tx": 8000,
        "download_bytes": 800,
        "upload_bytes": 300,
        "pkts_rx": 30,
        "pkts_tx": 80,
        "errors_rx": 0,
        "errors_tx": 0,
        "dropped_rx": 0,
        "dropped_tx": 0,
    }, db_path)

    # Yesterday — A downloads 500, uploads 150
    database.insert_sample({
        "timestamp": f"{yesterday_str}T20:00:00",
        "mac_address": MAC_A,
        "bytes_rx": 4000,
        "bytes_tx": 9000,
        "download_bytes": 500,
        "upload_bytes": 150,
        "pkts_rx": 50,
        "pkts_tx": 100,
        "errors_rx": 0,
        "errors_tx": 0,
        "dropped_rx": 0,
        "dropped_tx": 0,
    }, db_path)

    # 7 days ago — A downloads 200, uploads 50
    database.insert_sample({
        "timestamp": f"{seven_days_str}T15:00:00",
        "mac_address": MAC_A,
        "bytes_rx": 2000,
        "bytes_tx": 3000,
        "download_bytes": 200,
        "upload_bytes": 50,
        "pkts_rx": 20,
        "pkts_tx": 30,
        "errors_rx": 0,
        "errors_tx": 0,
        "dropped_rx": 0,
        "dropped_tx": 0,
    }, db_path)

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as test_client:
        yield test_client, MAC_A, MAC_B, today_str, yesterday_str

    object.__setattr__(cfg_module.config, "DATABASE_PATH", original_db)


# ==============================================================================
# Cache Headers
# ==============================================================================

def test_no_cache_headers_on_api_status(client):
    """All API responses must include no-store cache headers."""
    res = client.get("/api/status")
    assert res.status_code == 200
    cc = res.headers.get("Cache-Control", "")
    assert "no-store" in cc


def test_no_cache_headers_on_api_devices(client):
    res = client.get("/api/devices")
    assert "no-store" in res.headers.get("Cache-Control", "")


def test_no_cache_headers_on_usage(client):
    for endpoint in ["/api/usage/today", "/api/usage/hourly", "/api/network/stats"]:
        res = client.get(endpoint)
        assert "no-store" in res.headers.get("Cache-Control", ""), \
            f"Missing no-store on {endpoint}"


# ==============================================================================
# 1. /api/status
# ==============================================================================

def test_status_returns_200_and_online(client):
    """GET /api/status must return 200 with status=online."""
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "online"


def test_status_has_router_block(client):
    """GET /api/status must include router info block."""
    data = client.get("/api/status").get_json()
    assert "router" in data
    assert "host" in data["router"]
    assert "mode" in data["router"]


def test_status_has_system_block_with_timezone(client):
    """GET /api/status must include system block with IST timezone."""
    data = client.get("/api/status").get_json()
    assert "system" in data
    assert data["system"]["timezone"] == "Asia/Kolkata"
    assert "current_time_ist" in data["system"]


def test_status_has_collector_block(client):
    """GET /api/status must include collector block."""
    data = client.get("/api/status").get_json()
    assert "collector" in data
    assert "mode" in data["collector"]
    assert "collection_interval_seconds" in data["collector"]


def test_status_does_not_expose_password(client):
    """GET /api/status must never expose router credentials."""
    raw = client.get("/api/status").data.decode()
    assert "password" not in raw.lower()
    assert "ROUTER_PASSWORD" not in raw
    # Bearer/sysauth tokens must not appear
    assert "bearer" not in raw.lower()
    assert "sysauth" not in raw.lower()


def test_status_has_device_count(client):
    """GET /api/status includes known device count."""
    data = client.get("/api/status").get_json()
    assert "devices" in data
    assert "known_count" in data["devices"]
    assert data["devices"]["known_count"] == 0


# ==============================================================================
# 2. /api/devices
# ==============================================================================

def test_devices_empty_db(client):
    """GET /api/devices on empty database returns count=0 and empty list."""
    res = client.get("/api/devices")
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] == 0
    assert data["devices"] == []


def test_devices_returns_seeded_devices(seeded_client):
    """GET /api/devices returns all seeded devices with usage totals."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    res = tc.get("/api/devices")
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] == 2
    macs = {d["mac_address"] for d in data["devices"]}
    assert MAC_A in macs
    assert MAC_B in macs


def test_devices_includes_usage_fields(seeded_client):
    """GET /api/devices includes download_bytes, upload_bytes, total_bytes per device."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/devices").get_json()
    for dev in data["devices"]:
        assert "download_bytes" in dev
        assert "upload_bytes" in dev
        assert "total_bytes" in dev
        # total_bytes must equal download + upload
        assert dev["total_bytes"] == dev["download_bytes"] + dev["upload_bytes"]


def test_devices_download_upload_not_reversed(seeded_client):
    """
    CRITICAL: download_bytes must equal sum of download_bytes in DB (not upload).
    Verifies direction semantics are not reversed in the devices list.
    """
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/devices").get_json()
    dev_a = next(d for d in data["devices"] if d["mac_address"] == MAC_A)
    # MAC_A total: download=600+400+500+200=1700, upload=200+200+150+50=600
    assert dev_a["download_bytes"] == 1700
    assert dev_a["upload_bytes"] == 600


def test_devices_includes_identity_fields(seeded_client):
    """GET /api/devices must include hostname, IP, radio, SSID, AP, last_seen."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/devices").get_json()
    dev_a = next(d for d in data["devices"] if d["mac_address"] == MAC_A)
    assert dev_a["hostname"] == "Laptop-Alpha"
    assert dev_a["ip_address"] == "192.168.29.10"
    assert dev_a["radio"] == "5GHz"
    assert dev_a["ssid"] == "JioFiber-5G"
    assert "last_seen" in dev_a


# ==============================================================================
# 3. /api/usage/today
# ==============================================================================

def test_usage_today_structure_empty_db(client):
    """GET /api/usage/today returns correct structure with zeros on empty DB."""
    res = client.get("/api/usage/today")
    assert res.status_code == 200
    data = res.get_json()
    assert data["period"] == "today"
    assert "download_bytes" in data
    assert "upload_bytes" in data
    assert "total_bytes" in data
    assert "start" in data
    assert "end" in data
    assert data["download_bytes"] == 0
    assert data["upload_bytes"] == 0
    assert data["total_bytes"] == 0


def test_usage_today_correct_totals(seeded_client):
    """GET /api/usage/today aggregates only today's samples (IST boundary)."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/usage/today").get_json()
    # Today: A=1000 dl + 400 ul; B=800 dl + 300 ul → total dl=1800, ul=700
    assert data["download_bytes"] == 1800, f"Got {data['download_bytes']}"
    assert data["upload_bytes"] == 700, f"Got {data['upload_bytes']}"
    assert data["total_bytes"] == 2500


def test_usage_today_download_not_upload(seeded_client):
    """CRITICAL: today's download_bytes must not equal upload_bytes (direction check)."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/usage/today").get_json()
    assert data["download_bytes"] != data["upload_bytes"], \
        "download and upload are equal — possible direction reversal"
    assert data["download_bytes"] > data["upload_bytes"], \
        "download should be larger than upload in test data"


# ==============================================================================
# 4. /api/usage/yesterday
# ==============================================================================

def test_usage_yesterday_structure(client):
    """GET /api/usage/yesterday returns correct structure."""
    res = client.get("/api/usage/yesterday")
    assert res.status_code == 200
    data = res.get_json()
    assert data["period"] == "yesterday"
    assert "total_bytes" in data


def test_usage_yesterday_correct_totals(seeded_client):
    """GET /api/usage/yesterday returns only yesterday's data."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/usage/yesterday").get_json()
    # Only A has yesterday data: download=500, upload=150
    assert data["download_bytes"] == 500
    assert data["upload_bytes"] == 150
    assert data["total_bytes"] == 650


def test_usage_yesterday_excludes_today(seeded_client):
    """Yesterday's total must be strictly less than today's total."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    today_total = tc.get("/api/usage/today").get_json()["total_bytes"]
    yday_total = tc.get("/api/usage/yesterday").get_json()["total_bytes"]
    # Seeded data ensures this; verify they are different (not aggregated together)
    assert yday_total != today_total


# ==============================================================================
# 5. /api/usage/7days
# ==============================================================================

def test_usage_7days_structure(client):
    """GET /api/usage/7days returns correct structure."""
    res = client.get("/api/usage/7days")
    assert res.status_code == 200
    data = res.get_json()
    assert data["period"] == "7days"
    assert "total_bytes" in data
    assert "download_bytes" in data
    assert "upload_bytes" in data


def test_usage_7days_includes_all_window(seeded_client):
    """GET /api/usage/7days includes today, yesterday, and 6-days-ago samples."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/usage/7days").get_json()
    # All samples from last 7 days: A=(1700 dl, 600 ul), B=(800 dl, 300 ul)
    assert data["download_bytes"] == 2500
    assert data["upload_bytes"] == 900
    assert data["total_bytes"] == 3400


# ==============================================================================
# 6. /api/usage/month
# ==============================================================================

def test_usage_month_structure(client):
    """GET /api/usage/month returns correct structure."""
    res = client.get("/api/usage/month")
    assert res.status_code == 200
    data = res.get_json()
    assert data["period"] == "month"
    assert "total_bytes" in data


def test_usage_month_has_data(seeded_client):
    """Monthly totals must be non-zero and include today's data."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    month_data = tc.get("/api/usage/month").get_json()
    today_data = tc.get("/api/usage/today").get_json()
    # Month must include at least today's downloads
    assert month_data["download_bytes"] >= today_data["download_bytes"]
    assert month_data["upload_bytes"] >= today_data["upload_bytes"]
    assert month_data["total_bytes"] > 0


# ==============================================================================
# 7. /api/usage/daily
# ==============================================================================

def test_usage_daily_structure(client):
    """GET /api/usage/daily returns {days: [...]} structure."""
    res = client.get("/api/usage/daily")
    assert res.status_code == 200
    data = res.get_json()
    assert "days" in data
    assert isinstance(data["days"], list)


def test_usage_daily_empty_db_returns_empty_list(client):
    """GET /api/usage/daily on empty DB returns empty days list (not an error)."""
    data = client.get("/api/usage/daily").get_json()
    assert data["days"] == []


def test_usage_daily_entries_have_correct_fields(seeded_client):
    """Each daily entry must have date, download_bytes, upload_bytes, total_bytes."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/usage/daily").get_json()
    assert len(data["days"]) >= 1
    for entry in data["days"]:
        assert "date" in entry
        assert "download_bytes" in entry
        assert "upload_bytes" in entry
        assert "total_bytes" in entry
        assert entry["total_bytes"] == entry["download_bytes"] + entry["upload_bytes"]


def test_usage_daily_correct_per_day_totals(seeded_client):
    """Daily aggregates must be correct per calendar day."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/usage/daily").get_json()
    days_map = {d["date"]: d for d in data["days"]}

    assert today in days_map, f"Today ({today}) missing from daily"
    # Today: A=1000dl+400ul, B=800dl+300ul
    assert days_map[today]["download_bytes"] == 1800
    assert days_map[today]["upload_bytes"] == 700

    assert yesterday in days_map, f"Yesterday ({yesterday}) missing from daily"
    # Yesterday: A=500dl+150ul only
    assert days_map[yesterday]["download_bytes"] == 500


# ==============================================================================
# 8. /api/usage/hourly
# ==============================================================================

def test_hourly_always_returns_24_entries(client):
    """GET /api/usage/hourly must ALWAYS return exactly 24 hour entries."""
    res = client.get("/api/usage/hourly")
    assert res.status_code == 200
    data = res.get_json()
    assert "hours" in data
    assert len(data["hours"]) == 24


def test_hourly_first_hour_is_0000(client):
    """First entry in hourly response is 00:00."""
    data = client.get("/api/usage/hourly").get_json()
    assert data["hours"][0]["hour"] == "00:00"


def test_hourly_last_hour_is_2300(client):
    """Last entry in hourly response is 23:00."""
    data = client.get("/api/usage/hourly").get_json()
    assert data["hours"][23]["hour"] == "23:00"


def test_hourly_includes_date_and_timezone(client):
    """GET /api/usage/hourly includes date and timezone fields."""
    data = client.get("/api/usage/hourly").get_json()
    assert "date" in data
    assert "timezone" in data
    assert data["timezone"] == "Asia/Kolkata"


def test_hourly_empty_hours_have_zero_values(client):
    """Hours with no data must return zero values, not missing keys."""
    data = client.get("/api/usage/hourly").get_json()
    for entry in data["hours"]:
        assert "download_bytes" in entry
        assert "upload_bytes" in entry
        assert "total_bytes" in entry
        assert entry["download_bytes"] >= 0
        assert entry["upload_bytes"] >= 0


def test_hourly_seeded_data_appears_in_correct_hour(seeded_client):
    """Samples at 08:00 and 09:00 IST must appear in the correct hour buckets."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/usage/hourly").get_json()
    hours_map = {h["hour"]: h for h in data["hours"]}
    # 08:00: A downloaded 600, uploaded 200
    assert hours_map["08:00"]["download_bytes"] == 600
    assert hours_map["08:00"]["upload_bytes"] == 200
    # 09:00: A downloaded 400, uploaded 200
    assert hours_map["09:00"]["download_bytes"] == 400
    assert hours_map["09:00"]["upload_bytes"] == 200
    # 10:00: B downloaded 800, uploaded 300
    assert hours_map["10:00"]["download_bytes"] == 800
    assert hours_map["10:00"]["upload_bytes"] == 300


def test_hourly_total_equals_download_plus_upload(seeded_client):
    """Each hourly entry's total_bytes must equal download + upload."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/usage/hourly").get_json()
    for h in data["hours"]:
        assert h["total_bytes"] == h["download_bytes"] + h["upload_bytes"], \
            f"Hour {h['hour']}: total mismatch"


# ==============================================================================
# 9. /api/devices/<mac>
# ==============================================================================

def test_device_detail_404_when_not_found(client):
    """GET /api/devices/<mac> returns 404 when device doesn't exist."""
    res = client.get("/api/devices/AA:BB:CC:11:22:33")
    assert res.status_code == 404
    data = res.get_json()
    assert "error" in data


def test_device_detail_400_invalid_mac(client):
    """GET /api/devices/<mac> returns 400 for invalid MAC address format."""
    res = client.get("/api/devices/not-a-mac")
    assert res.status_code == 400
    data = res.get_json()
    assert "error" in data


def test_device_detail_400_mac_missing_octets(client):
    """Short MAC address returns 400."""
    res = client.get("/api/devices/AA:BB:CC")
    assert res.status_code == 400


def test_device_detail_returns_identity(seeded_client):
    """GET /api/devices/<mac> includes all identity fields."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}").get_json()
    assert data["mac_address"] == MAC_A
    assert data["hostname"] == "Laptop-Alpha"
    assert data["ip_address"] == "192.168.29.10"
    assert data["radio"] == "5GHz"
    assert data["ssid"] == "JioFiber-5G"
    assert "last_seen" in data
    assert "is_active" in data


def test_device_detail_has_usage_periods(seeded_client):
    """GET /api/devices/<mac> includes today/yesterday/7days/month/all_time breakdowns."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}").get_json()
    assert "usage" in data
    usage = data["usage"]
    for period in ["today", "yesterday", "last_7_days", "this_month", "all_time"]:
        assert period in usage, f"Missing period '{period}' in usage"
        assert "download_bytes" in usage[period]
        assert "upload_bytes" in usage[period]
        assert "total_bytes" in usage[period]


def test_device_detail_today_correct(seeded_client):
    """Today's period usage must reflect only today's samples."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}").get_json()
    # MAC_A today: dl=600+400=1000, ul=200+200=400
    assert data["usage"]["today"]["download_bytes"] == 1000
    assert data["usage"]["today"]["upload_bytes"] == 400
    assert data["usage"]["today"]["total_bytes"] == 1400


def test_device_detail_yesterday_correct(seeded_client):
    """Yesterday's period usage must reflect only yesterday's samples."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}").get_json()
    assert data["usage"]["yesterday"]["download_bytes"] == 500
    assert data["usage"]["yesterday"]["upload_bytes"] == 150
    assert data["usage"]["yesterday"]["total_bytes"] == 650


def test_device_detail_all_time_correct(seeded_client):
    """All-time totals aggregate all samples for the device."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}").get_json()
    # MAC_A all: dl=600+400+500+200=1700, ul=200+200+150+50=600
    assert data["usage"]["all_time"]["download_bytes"] == 1700
    assert data["usage"]["all_time"]["upload_bytes"] == 600
    assert data["usage"]["all_time"]["total_bytes"] == 2300


def test_device_detail_direction_not_reversed(seeded_client):
    """CRITICAL: device usage download must not equal upload (direction verification)."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}").get_json()
    dl = data["usage"]["all_time"]["download_bytes"]
    ul = data["usage"]["all_time"]["upload_bytes"]
    assert dl != ul, "download and upload are equal — possible direction reversal"
    assert dl > ul, "download should exceed upload in test data"


def test_device_detail_mac_case_insensitive(seeded_client):
    """GET /api/devices/<mac> normalizes lowercase MAC to uppercase."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    lower_mac = MAC_A.lower()
    res = tc.get(f"/api/devices/{lower_mac}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["mac_address"] == MAC_A  # Always returned uppercase


# ==============================================================================
# 10. /api/devices/<mac>/daily
# ==============================================================================

def test_device_daily_400_invalid_mac(client):
    """GET /api/devices/<mac>/daily returns 400 for invalid MAC."""
    res = client.get("/api/devices/not-valid/daily")
    assert res.status_code == 400


def test_device_daily_returns_7_days(seeded_client):
    """GET /api/devices/<mac>/daily always returns exactly 7 calendar days."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}/daily").get_json()
    assert "days" in data
    assert len(data["days"]) == 7


def test_device_daily_includes_mac_address(seeded_client):
    """GET /api/devices/<mac>/daily includes the mac_address field."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}/daily").get_json()
    assert data["mac_address"] == MAC_A


def test_device_daily_entries_have_correct_fields(seeded_client):
    """Each daily entry includes date, download_bytes, upload_bytes, total_bytes."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}/daily").get_json()
    for entry in data["days"]:
        assert "date" in entry
        assert "download_bytes" in entry
        assert "upload_bytes" in entry
        assert "total_bytes" in entry
        assert entry["total_bytes"] == entry["download_bytes"] + entry["upload_bytes"]


def test_device_daily_today_has_correct_totals(seeded_client):
    """Today's entry in device daily must match today's actual usage."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}/daily").get_json()
    days_map = {d["date"]: d for d in data["days"]}
    assert today in days_map
    assert days_map[today]["download_bytes"] == 1000
    assert days_map[today]["upload_bytes"] == 400


def test_device_daily_missing_days_are_zero_padded(seeded_client):
    """Days with no device data must appear with zero values (not missing)."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    # MAC_B only has today's data
    data = tc.get(f"/api/devices/{MAC_B}/daily").get_json()
    days_map = {d["date"]: d for d in data["days"]}
    # Yesterday for MAC_B should be zero
    assert days_map[yesterday]["download_bytes"] == 0
    assert days_map[yesterday]["upload_bytes"] == 0


# ==============================================================================
# 11. /api/devices/<mac>/stats
# ==============================================================================

def test_device_stats_400_invalid_mac(client):
    """GET /api/devices/<mac>/stats returns 400 for invalid MAC."""
    res = client.get("/api/devices/bad-mac/stats")
    assert res.status_code == 400


def test_device_stats_returns_all_fields(seeded_client):
    """GET /api/devices/<mac>/stats returns all required counter fields."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}/stats").get_json()
    required_fields = [
        "bytes_rx", "bytes_tx",
        "packets_rx", "packets_tx",
        "errors_rx", "errors_tx",
        "dropped_rx", "dropped_tx",
        "download_bytes", "upload_bytes",
        "total_bytes", "mac_address",
    ]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"


def test_device_stats_correct_values(seeded_client):
    """GET /api/devices/<mac>/stats aggregates all samples correctly."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}/stats").get_json()
    # MAC_A has 4 samples, download sum = 1700, upload sum = 600
    assert data["download_bytes"] == 1700
    assert data["upload_bytes"] == 600
    assert data["total_bytes"] == 2300
    assert data["mac_address"] == MAC_A


def test_device_stats_bytes_rx_tx_are_cumulative(seeded_client):
    """bytes_rx and bytes_tx are sum of raw cumulative counter snapshots."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get(f"/api/devices/{MAC_A}/stats").get_json()
    # bytes_rx: 5000+5400+4000+2000 = 16400
    assert data["bytes_rx"] == 16400
    # bytes_tx: 10000+11000+9000+3000 = 33000
    assert data["bytes_tx"] == 33000


def test_device_stats_no_samples_returns_zeros(client):
    """GET /api/devices/<mac>/stats with no samples returns zero values."""
    import database
    import config as cfg_module
    # Insert a device but no samples
    database.upsert_device({
        "mac_address": "FF:FF:FF:FF:FF:FF",
        "hostname": "Empty",
        "ip_address": "",
        "radio": "",
        "ssid": "",
        "ap": "",
    })
    data = client.get("/api/devices/FF:FF:FF:FF:FF:FF/stats").get_json()
    assert data["download_bytes"] == 0
    assert data["upload_bytes"] == 0
    assert data["total_bytes"] == 0


# ==============================================================================
# 12. /api/network/stats
# ==============================================================================

def test_network_stats_returns_200(client):
    """GET /api/network/stats returns 200."""
    res = client.get("/api/network/stats")
    assert res.status_code == 200


def test_network_stats_returns_all_fields(client):
    """GET /api/network/stats includes all required counter fields."""
    data = client.get("/api/network/stats").get_json()
    required = [
        "bytes_rx", "bytes_tx",
        "packets_rx", "packets_tx",
        "errors_rx", "errors_tx",
        "dropped_rx", "dropped_tx",
        "download_bytes", "upload_bytes",
    ]
    for field in required:
        assert field in data, f"Missing field: {field}"


def test_network_stats_zero_on_empty_db(client):
    """All network stats are zero on empty database."""
    data = client.get("/api/network/stats").get_json()
    for field in ["bytes_rx", "bytes_tx", "packets_rx", "packets_tx"]:
        assert data[field] == 0


def test_network_stats_aggregates_all_devices(seeded_client):
    """Network stats aggregate across all devices."""
    tc, MAC_A, MAC_B, today, yesterday = seeded_client
    data = tc.get("/api/network/stats").get_json()
    # All samples: download = 600+400+800+500+200 = 2500, upload = 200+200+300+150+50 = 900
    assert data["download_bytes"] == 2500
    assert data["upload_bytes"] == 900


# ==============================================================================
# Endpoint existence regression test
# ==============================================================================

@pytest.mark.parametrize("endpoint", [
    "/api/status",
    "/api/devices",
    "/api/usage/today",
    "/api/usage/yesterday",
    "/api/usage/7days",
    "/api/usage/month",
    "/api/usage/daily",
    "/api/usage/hourly",
    "/api/network/stats",
])
def test_all_required_endpoints_exist(client, endpoint):
    """Every required API endpoint must return 2xx (not 404 or 500)."""
    res = client.get(endpoint)
    assert res.status_code in (200, 204), \
        f"Endpoint {endpoint} returned {res.status_code}"
    # Must return valid JSON
    data = res.get_json()
    assert data is not None, f"Endpoint {endpoint} did not return JSON"


def test_device_endpoints_exist_with_valid_mac(client):
    """Device-specific endpoints must exist (return 404 for unknown MAC, not 500)."""
    mac = "AA:BB:CC:11:22:33"
    for path in [f"/api/devices/{mac}", f"/api/devices/{mac}/daily", f"/api/devices/{mac}/stats"]:
        res = client.get(path)
        assert res.status_code in (200, 404, 400), \
            f"Path {path} returned unexpected {res.status_code}"
        assert res.get_json() is not None
