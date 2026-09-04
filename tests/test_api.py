"""
API Regression and Functional Tests for Jio WiFi Data Tracker.

Verifies that all 12 required endpoints are operational,
return valid JSON, enforce no-cache headers, and handle edge cases.
"""

import os
import tempfile
import pytest
from flask import Flask

import database
from api import api_bp
from app import create_app


@pytest.fixture
def client():
    """Create Flask test client with an isolated temporary database."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    # Initialize schema
    database.init_db(db_path)

    # Patch config DATABASE_PATH
    import config
    original_db = config.config.DATABASE_PATH
    object.__setattr__(config.config, "DATABASE_PATH", db_path)

    app = create_app()
    app.config["TESTING"] = True
    
    with app.test_client() as test_client:
        yield test_client

    # Restore and cleanup
    object.__setattr__(config.config, "DATABASE_PATH", original_db)
    try:
        os.remove(db_path)
    except OSError:
        pass


def test_no_cache_headers_on_api(client):
    """Verify no-store caching headers exist on API responses."""
    res = client.get("/api/status")
    assert res.status_code == 200
    assert "no-store" in res.headers.get("Cache-Control", "")


def test_endpoint_status(client):
    """GET /api/status returns router and system info."""
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "online"
    assert "router" in data
    assert "system" in data
    assert data["system"]["timezone"] == "Asia/Kolkata"


def test_endpoint_devices_empty(client):
    """GET /api/devices returns structured empty list when no devices exist."""
    res = client.get("/api/devices")
    assert res.status_code == 200
    data = res.get_json()
    assert "devices" in data
    assert data["count"] == 0


def test_endpoint_usage_today(client):
    """GET /api/usage/today returns period structure."""
    res = client.get("/api/usage/today")
    assert res.status_code == 200
    data = res.get_json()
    assert data["period"] == "today"
    assert "download_bytes" in data
    assert "upload_bytes" in data
    assert "total_bytes" in data


def test_endpoint_usage_yesterday(client):
    """GET /api/usage/yesterday returns period structure."""
    res = client.get("/api/usage/yesterday")
    assert res.status_code == 200
    data = res.get_json()
    assert data["period"] == "yesterday"
    assert "total_bytes" in data


def test_endpoint_usage_7days(client):
    """GET /api/usage/7days returns 7-day range totals."""
    res = client.get("/api/usage/7days")
    assert res.status_code == 200
    data = res.get_json()
    assert data["period"] == "7days"
    assert "total_bytes" in data


def test_endpoint_usage_month(client):
    """GET /api/usage/month returns current month totals."""
    res = client.get("/api/usage/month")
    assert res.status_code == 200
    data = res.get_json()
    assert data["period"] == "month"
    assert "total_bytes" in data


def test_endpoint_usage_daily(client):
    """GET /api/usage/daily returns list of daily buckets."""
    res = client.get("/api/usage/daily")
    assert res.status_code == 200
    data = res.get_json()
    assert "days" in data
    assert isinstance(data["days"], list)


def test_endpoint_usage_hourly_has_full_24_hours(client):
    """
    GET /api/usage/hourly MUST return complete 24 hours (00:00 to 23:00)
    regardless of current hour.
    """
    res = client.get("/api/usage/hourly")
    assert res.status_code == 200
    data = res.get_json()
    assert "hours" in data
    assert len(data["hours"]) == 24
    # Verify first and last hour
    assert data["hours"][0]["hour"] == "00:00"
    assert data["hours"][23]["hour"] == "23:00"


def test_endpoint_device_detail_and_stats(client):
    """Test device endpoints: /api/devices/<mac>, daily, stats."""
    mac = "AA:BB:CC:11:22:33"
    
    # 404 when not found
    res404 = client.get(f"/api/devices/{mac}")
    assert res404.status_code == 404

    # Seed device and traffic
    database.upsert_device({
        "mac_address": mac,
        "hostname": "Test-Laptop",
        "ip_address": "192.168.29.15",
        "radio": "5GHz",
        "ssid": "JioFiber-5G",
        "ap": "AP1"
    })
    database.insert_sample({
        "timestamp": "2026-09-04T10:00:00+05:30",
        "mac_address": mac,
        "bytes_rx": 100,
        "bytes_tx": 200,
        "download_bytes": 200,
        "upload_bytes": 100,
        "pkts_rx": 5,
        "pkts_tx": 10
    })

    # GET /api/devices/<mac>
    res = client.get(f"/api/devices/{mac}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["mac_address"] == mac
    assert data["download_bytes"] == 200
    assert data["upload_bytes"] == 100
    assert data["total_bytes"] == 300

    # GET /api/devices/<mac>/daily
    res_daily = client.get(f"/api/devices/{mac}/daily")
    assert res_daily.status_code == 200
    daily_data = res_daily.get_json()
    assert len(daily_data["days"]) == 7

    # GET /api/devices/<mac>/stats
    res_stats = client.get(f"/api/devices/{mac}/stats")
    assert res_stats.status_code == 200
    stats_data = res_stats.get_json()
    assert stats_data["mac_address"] == mac
    assert stats_data["download_bytes"] == 200
    assert stats_data["upload_bytes"] == 100


def test_endpoint_network_stats(client):
    """GET /api/network/stats returns network level counters."""
    res = client.get("/api/network/stats")
    assert res.status_code == 200
    data = res.get_json()
    for field in ["bytes_rx", "bytes_tx", "packets_rx", "packets_tx", "errors_rx", "errors_tx", "dropped_rx", "dropped_tx"]:
        assert field in data
