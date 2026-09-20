"""
Unit tests for configuration module (Phase 2).
"""

import importlib
import os
import pytest
from unittest.mock import patch

import config as config_module
from config import Config, load_env_file, configure_logging


def test_default_config_properties():
    """Verify default config values by reloading module with clean environment."""
    with patch.dict("os.environ", {}, clear=True):
        # Reload module so Config class defaults are evaluated against clean env
        reloaded = importlib.reload(config_module)
        cfg = reloaded.Config()
        assert cfg.ROUTER_HOST == "192.168.29.1"
        assert cfg.ROUTER_USERNAME == "admin"
        assert cfg.TIMEZONE == "Asia/Kolkata"
        assert cfg.DATA_RETENTION_DAYS == 0
        assert cfg.is_mock is True
        assert cfg.BILLING_CYCLE_DAY == 21
        assert cfg.BILLING_DATA_LIMIT_GB == 1000


def test_config_validation_valid():
    """Verify that default config passes validation."""
    cfg = Config()
    cfg.validate()  # Should not raise


def test_config_validation_invalid_host():
    """Verify validation fails on empty host."""
    cfg = Config(ROUTER_HOST="")
    with pytest.raises(ValueError, match="ROUTER_HOST"):
        cfg.validate()


def test_config_validation_invalid_mode():
    """Verify validation fails on unsupported mode."""
    cfg = Config(MODE="invalid_mode")
    with pytest.raises(ValueError, match="Invalid MODE"):
        cfg.validate()


def test_config_validation_invalid_retention():
    """Verify validation fails on negative retention days."""
    cfg = Config(DATA_RETENTION_DAYS=-5)
    with pytest.raises(ValueError, match="DATA_RETENTION_DAYS"):
        cfg.validate()


def test_config_validation_invalid_billing_day():
    """Verify validation fails on invalid billing cycle day."""
    cfg = Config(BILLING_CYCLE_DAY=0)
    with pytest.raises(ValueError, match="BILLING_CYCLE_DAY"):
        cfg.validate()
    cfg = Config(BILLING_CYCLE_DAY=29)
    with pytest.raises(ValueError, match="BILLING_CYCLE_DAY"):
        cfg.validate()


def test_config_validation_invalid_billing_limit():
    """Verify validation fails on invalid billing data limit."""
    cfg = Config(BILLING_DATA_LIMIT_GB=0)
    with pytest.raises(ValueError, match="BILLING_DATA_LIMIT_GB"):
        cfg.validate()
    cfg = Config(BILLING_DATA_LIMIT_GB=-10)
    with pytest.raises(ValueError, match="BILLING_DATA_LIMIT_GB"):
        cfg.validate()


def test_to_safe_dict_never_exposes_password():
    """Verify router password is excluded from dictionary representation."""
    cfg = Config(ROUTER_PASSWORD="SuperSecretPassword123")
    safe = cfg.to_safe_dict()
    assert "ROUTER_PASSWORD" not in safe
    assert "router_password" not in safe
    assert "password" not in safe
    assert "SuperSecretPassword123" not in str(safe)


def test_to_safe_dict_includes_billing_config():
    """Verify billing cycle config is included in safe dict."""
    cfg = Config(BILLING_CYCLE_DAY=15, BILLING_DATA_LIMIT_GB=500)
    safe = cfg.to_safe_dict()
    assert safe["billing_cycle_day"] == 15
    assert safe["billing_data_limit_gb"] == 500


def test_configure_logging():
    """Verify logging setup does not error."""
    cfg = Config(LOG_LEVEL="DEBUG")
    configure_logging(cfg)
