"""
Configuration module for Jio WiFi Data Tracker.

Loads configuration from environment variables with safe defaults.
Optimized for Raspberry Pi Zero 2 W with minimal overhead.
"""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(dotenv_path: str = ".env") -> None:
    """Minimal .env file loader to avoid external dependency."""
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
_load_env_file()


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
    
    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "5000"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    @property
    def is_mock(self) -> bool:
        """Check if operating in mock mode."""
        return self.MODE != "real"

    def to_safe_dict(self) -> dict:
        """Return safe configuration dictionary without exposing credentials."""
        return {
            "mode": self.MODE,
            "router_host": self.ROUTER_HOST,
            "router_username": self.ROUTER_USERNAME,
            "collection_interval": self.COLLECTION_INTERVAL,
            "dashboard_refresh_interval": self.DASHBOARD_REFRESH_INTERVAL,
            "timezone": self.TIMEZONE,
            "database_path": self.DATABASE_PATH,
            "host": self.HOST,
            "port": self.PORT,
            "log_level": self.LOG_LEVEL,
        }


# Singleton configuration instance
config = Config()
