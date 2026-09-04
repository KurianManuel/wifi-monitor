"""
Main application entry point for Jio WiFi Data Tracker.

Serves the read-only Flask API and static web dashboard.
Optimized for Raspberry Pi Zero 2 W.
"""

import logging
import os
import sys
from pathlib import Path

from flask import Flask, send_from_directory

import database
from api import api_bp
from config import config

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("jio_wifi_tracker")

# Base directory
BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = BASE_DIR / "dashboard"


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder=str(DASHBOARD_DIR), static_url_path="")
    
    # Register API blueprint under /api
    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        """Serve the terminal-styled web dashboard."""
        return send_from_directory(str(DASHBOARD_DIR), "index.html")

    @app.route("/<path:filename>")
    def static_files(filename: str):
        """Serve dashboard static assets (CSS, JS, fonts)."""
        return send_from_directory(str(DASHBOARD_DIR), filename)

    # Initialize database
    try:
        database.init_db()
        logger.info("Database initialized successfully at %s", config.DATABASE_PATH)
    except Exception as e:
        logger.critical("Database initialization failed: %s", e, exc_info=True)

    return app


app = create_app()

if __name__ == "__main__":
    logger.info("Starting Jio WiFi Data Tracker (Mode: %s, Timezone: %s)", config.MODE, config.TIMEZONE)
    logger.info("Dashboard available at http://%s:%d", config.HOST, config.PORT)
    app.run(host=config.HOST, port=config.PORT, debug=False)
