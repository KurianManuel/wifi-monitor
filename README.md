# Jio WiFi Data Tracker

A lightweight, reliable network telemetry and traffic monitoring system purpose-built for **JioFiber** and **JioAirFiber** home gateway routers running primarily on the **Raspberry Pi Zero 2 W** (and compatible Linux/Windows environments).

> [!IMPORTANT]
> **Router Dependency Notice**: This application communicates directly with Jio router firmware. The authentication mechanism, session lifecycle, router API calls, and counter telemetry are **strictly specific to JioFiber and JioAirFiber routers**. It is not compatible with generic off-the-shelf third-party routers without a custom driver.

---

## System Architecture

```
JIO FIBER / JIO AIRFIBER ROUTER
              |
              v
          login.py (Authentication & Session Validation)
              |
              v
     Authenticated Session
              |
              v
         collector.py (Periodic Polling & Delta Calculation)
              |
              v
          database.py (SQLite with WAL mode)
              |
              v
            api.py (Read-Only Flask API Blueprint)
              |
              v
         Web Dashboard (Terminal-inspired Vanilla JS / HTML / CSS)
```

The web dashboard **never** communicates directly with the router; it interacts exclusively with the read-only Flask API.

---

## Critical Direction Semantics

The system strictly interprets Jio router interface counters with the following persistent mapping:

$$\text{download\_bytes} = \Delta(\text{router current\_tx})$$
$$\text{upload\_bytes} = \Delta(\text{router current\_rx})$$

This convention is uniformly enforced across `collector.py`, `database.py`, `api.py`, and all frontend views.

---

## Core Project Layout

```
wifi-monitor/
├── app.py                  # Flask web server & static file host
├── api.py                  # Read-only REST API with 12 monitoring endpoints
├── database.py             # SQLite WAL-mode schema, indexes & queries
├── collector.py            # Traffic collector & delta calculation engine
├── login.py                # Jio router authentication interface & session holder
├── logout.py               # Jio router session termination interface
├── config.py               # Application configuration & safe env loader
├── requirements.txt        # Minimal Python dependencies
├── .env.example            # Environment configuration template
├── .gitignore              # Protects secrets, databases, and logs
├── data/                   # SQLite database storage directory
├── dashboard/
│   ├── index.html          # Semantic, accessible technical dashboard UI
│   ├── dashboard.js        # Modular client script (IST clock, charts, widgets)
│   └── dashboard.css       # High-contrast terminal design (#F06021, #6B9CAA)
└── tests/
    ├── test_api.py         # Regression tests for all 12 API endpoints
    └── test_database.py    # SQLite schema and aggregation unit tests
```

---

## Installation & Setup

### 1. Prerequisites
- Python 3.9+ (Python 3.11+ recommended for Raspberry Pi OS)
- Git

### 2. Clone and Setup Environment
```bash
git clone <repo-url> wifi-monitor
cd wifi-monitor

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .\.venv\Scripts\Activate.ps1

# Install minimal dependencies
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` to configure your router IP and credentials:
```ini
ROUTER_HOST=192.168.29.1
ROUTER_USERNAME=admin
ROUTER_PASSWORD=your_router_password

MODE=mock                     # Use 'mock' for testing without a router, 'real' on live Pi
COLLECTION_INTERVAL=60        # Seconds between polling cycles
DASHBOARD_REFRESH_INTERVAL=15 # Seconds between UI updates
TIMEZONE=Asia/Kolkata         # All date/time calculations use IST
DATABASE_PATH=data/traffic.db
PORT=5000
```

> [!CAUTION]
> Never commit `.env` or hardcode router passwords in code, logs, or dashboard templates.

---

## Read-Only API Endpoints

All endpoints return JSON and enforce `Cache-Control: no-store`:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/status` | Router connectivity & system status |
| `GET` | `/api/devices` | All active and registered devices with usage |
| `GET` | `/api/usage/today` | Today's total download & upload (IST) |
| `GET` | `/api/usage/yesterday` | Yesterday's total download & upload (IST) |
| `GET` | `/api/usage/7days` | Past 7 calendar days total usage |
| `GET` | `/api/usage/month` | Current month total usage |
| `GET` | `/api/usage/daily` | Aggregated daily usage buckets (last 30 days) |
| `GET` | `/api/usage/hourly` | Full 24-hour timeline for today (00:00 - 23:00) |
| `GET` | `/api/devices/<mac>` | Details & cumulative usage for a single MAC |
| `GET` | `/api/devices/<mac>/daily` | Last 7 calendar days usage for a single MAC |
| `GET` | `/api/devices/<mac>/stats` | Packet, error, and drop counters for a MAC |
| `GET` | `/api/network/stats` | Router network-level packet counters & errors |

---

## Testing & Verification

Run the test suite:
```bash
pytest
```

Run Python syntax checks:
```bash
python -m py_compile *.py
```

Inspect the database:
```bash
sqlite3 data/traffic.db ".tables"
sqlite3 data/traffic.db "SELECT * FROM traffic_samples ORDER BY id DESC LIMIT 5;"
```

---

## Raspberry Pi Zero 2 W Deployment (systemd)

Create `/etc/systemd/system/jio-monitor.service`:
```ini
[Unit]
Description=Jio WiFi Data Tracker Service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/wifi-monitor
ExecStart=/home/pi/wifi-monitor/.venv/bin/python app.py
Restart=always
RestartSec=10
EnvironmentFile=/home/pi/wifi-monitor/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable jio-monitor
sudo systemctl start jio-monitor
```
