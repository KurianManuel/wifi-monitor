"""
Configuration module for Jio WiFi Data Tracker.

Loads configuration from environment variables with safe defaults.
Optimized for Raspberry Pi Zero 2 W with minimal overhead.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def load_env_file(dotenv_path: str = ".env") -> None:
    """Minimal .env file loader avoiding heavy third-party dependencies."""
    env_file = Path(dotenv_path)
    if not env_file.is_file():
        return
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


# Load local .env if present
load_env_file()


@dataclass(frozen=True)
class Config:
    """Immutable application configuration."""
    
    # Router Settings
    ROUTER_HOST: str = os.getenv("ROUTER_HOST", "192.168.29.1")
    ROUTER_USERNAME: str = os.getenv("ROUTER_USERNAME", "admin")
    ROUTER_PASSWORD: str = os.getenv("ROUTER_PASSWORD", "")
    
    # Operation Mode: 'mock' or 'real'
    MODE: str = os.getenv("MODE", "mock").lower()
    
    # Timing (Seconds)
    COLLECTION_INTERVAL: int = int(os.getenv("COLLECTION_INTERVAL", "60"))
    DASHBOARD_REFRESH_INTERVAL: int = int(os.getenv("DASHBOARD_REFRESH_INTERVAL", "15"))
    
    # Timezone: Must be Asia/Kolkata (IST)
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")
    
    # Database
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/traffic.db")
    DATA_RETENTION_DAYS: int = int(os.getenv("DATA_RETENTION_DAYS", "0"))  # 0 = retain indefinitely

    # Billing Cycle (AirFiber)
    BILLING_CYCLE_DAY: int = int(os.getenv("BILLING_CYCLE_DAY", "21"))
    BILLING_DATA_LIMIT_GB: int = int(os.getenv("BILLING_DATA_LIMIT_GB", "1000"))

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "5000"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    @property
    def is_mock(self) -> bool:
        """Check if operating in mock mode."""
        return self.MODE != "real"

    def validate(self) -> None:
        """Validate configuration settings for sanity."""
        if not self.ROUTER_HOST:
            raise ValueError("ROUTER_HOST must not be empty.")
        if self.COLLECTION_INTERVAL < 1:
            raise ValueError("COLLECTION_INTERVAL must be at least 1 second.")
        if self.DASHBOARD_REFRESH_INTERVAL < 1:
            raise ValueError("DASHBOARD_REFRESH_INTERVAL must be at least 1 second.")
        if self.MODE not in ("mock", "real"):
            raise ValueError(f"Invalid MODE: '{self.MODE}'. Must be 'mock' or 'real'.")
        if self.DATA_RETENTION_DAYS < 0:
            raise ValueError("DATA_RETENTION_DAYS cannot be negative.")
        if not (1 <= self.BILLING_CYCLE_DAY <= 28):
            raise ValueError("BILLING_CYCLE_DAY must be between 1 and 28.")
        if self.BILLING_DATA_LIMIT_GB < 1:
            raise ValueError("BILLING_DATA_LIMIT_GB must be at least 1.")

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return safe configuration dictionary without exposing credentials."""
        return {
            "mode": self.MODE,
            "router_host": self.ROUTER_HOST,
            "router_username": self.ROUTER_USERNAME,
            "collection_interval": self.COLLECTION_INTERVAL,
            "dashboard_refresh_interval": self.DASHBOARD_REFRESH_INTERVAL,
            "timezone": self.TIMEZONE,
            "database_path": self.DATABASE_PATH,
            "data_retention_days": self.DATA_RETENTION_DAYS,
            "billing_cycle_day": self.BILLING_CYCLE_DAY,
            "billing_data_limit_gb": self.BILLING_DATA_LIMIT_GB,
            "host": self.HOST,
            "port": self.PORT,
            "log_level": self.LOG_LEVEL,
        }


def configure_logging(cfg: Optional[Config] = None) -> None:
    """Configure structured logging according to configuration."""
    active_cfg = cfg or config
    level = getattr(logging, active_cfg.LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True
    )


# Singleton configuration instance
config = Config()
