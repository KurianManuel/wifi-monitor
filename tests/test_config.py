"""
Unit tests for configuration module (Phase 2).
"""

import os
import pytest
from config import Config, load_env_file, configure_logging


def test_default_config_properties():
    """Verify default config values."""
    cfg = Config()
    assert cfg.ROUTER_HOST == "192.168.29.1"
    assert cfg.ROUTER_USERNAME == "admin"
    assert cfg.TIMEZONE == "Asia/Kolkata"
    assert cfg.DATA_RETENTION_DAYS == 0
    assert cfg.is_mock is True


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


def test_to_safe_dict_never_exposes_password():
    """Verify router password is excluded from dictionary representation."""
    cfg = Config(ROUTER_PASSWORD="SuperSecretPassword123")
    safe = cfg.to_safe_dict()
    assert "ROUTER_PASSWORD" not in safe
    assert "router_password" not in safe
    assert "password" not in safe
    assert "SuperSecretPassword123" not in str(safe)


def test_configure_logging():
    """Verify logging setup does not error."""
    cfg = Config(LOG_LEVEL="DEBUG")
    configure_logging(cfg)
