// ============================================================
// WiFi Monitor Dashboard
// Terminal-inspired dark UI
// ============================================================

const API = "/api";
const IST_TIMEZONE = "Asia/Kolkata";

// ============================================================
// State
// ============================================================

let devices = [];
let todayUsage = null;
let dailyHistory = [];
let hourlyHistory = [];
let networkStats = null;
let selectedDevice = null;
let currentView = "overview";

// ============================================================
// Usage distribution palette
// ============================================================

const DEVICE_COLORS = [
    "#F06021",
    "#6B9CAA",
    "#7E8CE0",
    "#C17BDE",
    "#5FAF8F",
    "#D4A84F",
    "#D66A8A",
    "#7FA8C9"
];

// ============================================================
// DOM helpers
// ============================================================

function $(id) {
    return document.getElementById(id);
}

function setText(id, value) {
    const el = $(id);
    if (!el) return;
    el.textContent = (value === null || value === undefined || value === "") ? "--" : value;
}

function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

// ============================================================
// Formatting helpers
// ============================================================

function formatBytes(bytes) {
    bytes = Number(bytes || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(2)} KB`;
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(2)} MB`;
    if (bytes < 1024 ** 4) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
    return `${(bytes / 1024 ** 4).toFixed(2)} TB`;
}

function formatAxisBytes(bytes) {
    bytes = Number(bytes || 0);
    if (bytes === 0) return "0 B";
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
    return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function percentage(value, total) {
    value = Number(value || 0);
    total = Number(total || 0);
    if (!total) return "0.0%";
    return `${((value / total) * 100).toFixed(1)}%`;
}

function formatNumber(value) {
    return Number(value || 0).toLocaleString("en-IN");
}

function getDeviceColor(index) {
    return DEVICE_COLORS[index % DEVICE_COLORS.length];
}

function timeAgo(timestamp) {
    if (!timestamp) return "--";
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return "--";

    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
    if (seconds < 10) return "JUST NOW";
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

function formatDateTime(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);

    return date.toLocaleString("en-IN", {
        timeZone: IST_TIMEZONE,
        year: "2-digit",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
    });
}

function getISTDateParts() {
    const formatter = new Intl.DateTimeFormat("en-CA", {
        timeZone: IST_TIMEZONE,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
    });

    const parts = formatter.formatToParts(new Date());
    const result = {};
    parts.forEach(part => {
        if (part.type !== "literal") {
            result[part.type] = part.value;
        }
    });
    return result;
}

function updateClock() {
    const parts = getISTDateParts();
    const value = `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
    if ($("clock")) {
        $("clock").textContent = value;
    }
}

// ============================================================
// API helper
// ============================================================

async function getJSON(path) {
    const cleanPath = path.startsWith("/") ? path : `/${path}`;
    const url = `${API}${cleanPath}`;
    const response = await fetch(url, {
        cache: "no-store",
        headers: { "Accept": "application/json" }
    });
    if (!response.ok) {
        throw new Error(`${url} returned HTTP ${response.status}`);
    }
    return await response.json();
}

// ============================================================
// Loaders
// ============================================================

async function loadStatus() {
    try {
        const data = await getJSON("/status");
        setText("api", "CONNECTED");
        setText("database", "CONNECTED");
        setText("collector", data.collector?.mode ? "CONNECTED" : "CONNECTED");

        const isOnline = data.status === "online" || data.router?.connected;
        setText("router", isOnline ? "ONLINE" : "OFFLINE");
        setText("netRouterApi", isOnline ? "ONLINE" : "OFFLINE");

        const routerIdentity = data.router?.identity || "ARACKAL NETWORK";
        if ($("sidebarNetworkName")) $("sidebarNetworkName").textContent = routerIdentity;
        if ($("headerNetworkName")) $("headerNetworkName").textContent = routerIdentity;

        if ($("updated")) $("updated").textContent = "JUST NOW";

        if ($("cfgHost")) $("cfgHost").textContent = data.router?.host || "192.168.29.1";
        if ($("cfgInterval")) $("cfgInterval").textContent = `${data.collector?.collection_interval_seconds || 60} seconds`;
        if ($("cfgRefresh")) $("cfgRefresh").textContent = `${data.system?.dashboard_refresh_interval_seconds || 15} seconds`;

        return data;
    } catch (err) {
        console.error("Status error:", err);
        setText("api", "OFFLINE");
        setText("database", "UNKNOWN");
        setText("collector", "UNKNOWN");
        setText("router", "OFFLINE");
        setText("netRouterApi", "OFFLINE");
    }
}

async function loadDevices() {
    try {
        const data = await getJSON("/devices");
        devices = Array.isArray(data) ? data : (data.devices || []);
        renderOverviewDeviceTable(devices);
        renderAllDevices(devices);
        setText("ndev", devices.length);
        setText("count", devices.length);
        setText("split", `${devices.length} STORED DEVICES`);
        return devices;
    } catch (err) {
        console.error("Devices error:", err);
    }
}

async function loadTodayUsage() {
    try {
        const data = await getJSON("/usage/today");
        todayUsage = data || { download_bytes: 0, upload_bytes: 0, total_bytes: 0 };
        renderTodayUsage();
        return todayUsage;
    } catch (err) {
        console.error("Today usage error:", err);
    }
}

function renderTodayUsage() {
    if (!todayUsage) return;

    const total = Number(todayUsage.total_bytes || (Number(todayUsage.download_bytes || 0) + Number(todayUsage.upload_bytes || 0)));
    const dl = Number(todayUsage.download_bytes || 0);
    const ul = Number(todayUsage.upload_bytes || 0);

    setText("total", formatBytes(total));
    setText("download", formatBytes(dl));
    setText("upload", formatBytes(ul));
    setText("td", formatBytes(dl));
    setText("tu", formatBytes(ul));
    setText("dp", `${percentage(dl, total)} OF TOTAL`);
    setText("up", `${percentage(ul, total)} OF TOTAL`);

    setText("nd", formatBytes(dl));
    setText("nu", formatBytes(ul));
    setText("nt", formatBytes(total));

    if ($("donutText")) {
        $("donutText").textContent = formatBytes(total);
    }

    renderDistribution(devices, total);
}

// ============================================================
// Usage distribution
// ============================================================

function renderDistribution(list, total) {
    const container = $("distribution");
    const donut = $("donut");
    if (!container || !donut) return;

    container.innerHTML = "";

    if (!list || !list.length || total <= 0) {
        donut.style.background = "conic-gradient(#4D4D4D 0deg 360deg)";
        if ($("donutText")) $("donutText").textContent = "0 B";
        container.innerHTML = `<div class="pending">NO USAGE RECORDED YET</div>`;
        return;
    }

    const sorted = [...list]
        .sort((a, b) => Number(b.total_bytes || 0) - Number(a.total_bytes || 0))
        .filter(d => Number(d.total_bytes || 0) > 0);

    if (!sorted.length) {
        donut.style.background = "conic-gradient(#4D4D4D 0deg 360deg)";
        container.innerHTML = `<div class="pending">NO USAGE RECORDED YET</div>`;
        return;
    }

    let currentAngle = 0;
    const segments = [];

    sorted.forEach((device, index) => {
        const value = Number(device.total_bytes || 0);
        const angle = (value / total) * 360;
        const color = getDeviceColor(index);
        segments.push(`${color} ${currentAngle}deg ${currentAngle + angle}deg`);
        currentAngle += angle;
    });

    if (currentAngle < 360) {
        segments.push(`#4D4D4D ${currentAngle}deg 360deg`);
    }

    donut.style.background = `conic-gradient(${segments.join(", ")})`;

    sorted.forEach((device, index) => {
        const value = Number(device.total_bytes || 0);
        const color = getDeviceColor(index);
        const row = document.createElement("div");
        row.className = "distribution-row";
        row.innerHTML = `
            <span class="distribution-dot" style="background:${color}"></span>
            <span class="distribution-name">${escapeHtml(device.hostname || device.mac_address || "Unknown")}</span>
            <strong>${escapeHtml(formatBytes(value))}</strong>
        `;
        container.appendChild(row);
    });
}

// ============================================================
// Overview & All Devices Tables
// ============================================================

function renderOverviewDeviceTable(list) {
    const tbody = $("deviceRows");
    if (!tbody) return;

    const sorted = [...list].sort((a, b) => Number(b.total_bytes || 0) - Number(a.total_bytes || 0));
    tbody.innerHTML = "";

    sorted.forEach(device => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>
                <button class="device-link" data-mac="${escapeHtml(device.mac_address)}">
                    <span class="status-dot ${device.is_active ? '' : 'offline'}"></span>
                    ${escapeHtml(device.hostname || "Unknown")}
                </button>
            </td>
            <td>${escapeHtml(device.ip_address || device.ipv4_address || "--")}</td>
            <td class="orange">${escapeHtml(formatBytes(device.download_bytes || 0))}</td>
            <td class="teal">${escapeHtml(formatBytes(device.upload_bytes || 0))}</td>
            <td>${escapeHtml(formatBytes(device.total_bytes || 0))}</td>
            <td>${escapeHtml(timeAgo(device.last_seen))}</td>
        `;
        tbody.appendChild(row);
    });

    attachDeviceLinks(tbody);
    setText("dc", `(${sorted.length})`);
}

function renderAllDevices(list) {
    const tbody = $("allRows");
    if (!tbody) return;

    tbody.innerHTML = "";

    list.forEach(device => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>
                <button class="device-link" data-mac="${escapeHtml(device.mac_address)}">
                    <span class="status-dot ${device.is_active ? '' : 'offline'}"></span>
                    ${escapeHtml(device.hostname || "Unknown")}
                </button>
            </td>
            <td><code>${escapeHtml(device.mac_address || "--")}</code></td>
            <td>${escapeHtml(device.ip_address || device.ipv4_address || "--")}</td>
            <td>${escapeHtml(device.radio || "--")}</td>
            <td>${escapeHtml(device.ssid || "--")}</td>
            <td>${escapeHtml(device.ap || device.ap_name || "--")}</td>
            <td>${escapeHtml(timeAgo(device.last_seen))}</td>
        `;
        tbody.appendChild(row);
    });

    attachDeviceLinks(tbody);
}

function attachDeviceLinks(container) {
    container.querySelectorAll(".device-link").forEach(btn => {
        btn.addEventListener("click", () => {
            openDevice(btn.dataset.mac);
        });
    });
}

// ============================================================
// Hourly Network Usage Chart
// Complete 00:00 to 23:00 (24-hour timeline)
// ============================================================

async function loadHourlyUsage() {
    try {
        const data = await getJSON("/usage/hourly");
        hourlyHistory = data.hours || data.history || [];
        renderHourlyChart();
    } catch (err) {
        console.error("Hourly usage error:", err);
        const box = $("hourlyChartContainer") || document.querySelector(".chartbox");
        if (box) box.innerHTML = `<div class="pending">HOURLY DATA UNAVAILABLE</div>`;
    }
}

function renderHourlyChart() {
    const box = $("hourlyChartContainer") || document.querySelector(".chartbox");
    if (!box) return;

    const width = 1000;
    const height = 390;
    const paddingLeft = 92;
    const paddingRight = 30;
    const paddingTop = 30;
    const paddingBottom = 62;

    const graphWidth = width - paddingLeft - paddingRight;
    const graphHeight = height - paddingTop - paddingBottom;

    const ist = getISTDateParts();

    // Map existing hours
    const hourlyMap = {};
    (hourlyHistory || []).forEach(item => {
        let hourNum = null;
        if (item.hour !== undefined) {
            const m = String(item.hour).match(/(\d{2}):\d{2}/);
            if (m) hourNum = Number(m[1]);
            else hourNum = Number(item.hour);
        }
        if (hourNum !== null && hourNum >= 0 && hourNum <= 23) {
            hourlyMap[hourNum] = {
                download: Number(item.download_bytes || 0),
                upload: Number(item.upload_bytes || 0)
            };
        }
    });

    // Build points for all 24 hours (0 to 23)
    const points = [];
    for (let hour = 0; hour < 24; hour++) {
        const val = hourlyMap[hour] || { download: 0, upload: 0 };
        points.push({
            hour,
            download: val.download,
            upload: val.upload
        });
    }

    const maxData = Math.max(...points.map(p => Math.max(p.download, p.upload)), 1);
    let maxValue = maxData * 1.15;
    if (maxValue < 1024 ** 2) maxValue = 1024 ** 2;

    function xForHour(hour) {
        return paddingLeft + (hour / 24) * graphWidth;
    }

    function yForValue(val) {
        return paddingTop + graphHeight - (val / maxValue) * graphHeight;
    }

    // Grid lines (horizontal)
    let grid = "";
    for (let i = 0; i <= 5; i++) {
        const ratio = i / 5;
        const y = paddingTop + graphHeight - ratio * graphHeight;
        const val = maxValue * ratio;
        grid += `
            <line x1="${paddingLeft}" y1="${y}" x2="${width - paddingRight}" y2="${y}" class="chart-grid" />
            <text x="${paddingLeft - 16}" y="${y + 5}" text-anchor="end" class="chart-label chart-y-label">
                ${escapeHtml(formatAxisBytes(val))}
            </text>
        `;
    }

    // Grid hours (vertical)
    const gridHours = [0, 4, 8, 12, 16, 20, 24];
    gridHours.forEach(hour => {
        const x = xForHour(hour);
        grid += `<line x1="${x}" y1="${paddingTop}" x2="${x}" y2="${paddingTop + graphHeight}" class="chart-grid chart-grid-vertical" />`;
    });

    // X axis labels
    let xLabels = "";
    gridHours.forEach(hour => {
        const x = xForHour(hour);
        const label = `${String(hour).padStart(2, "0")}:00`;
        let anchor = "middle";
        if (hour === 0) anchor = "start";
        if (hour === 24) anchor = "end";
        xLabels += `<text x="${x}" y="${height - 18}" text-anchor="${anchor}" class="chart-label chart-x-label">${label}</text>`;
    });

    // Points & Lines
    const downloadPoints = [];
    const uploadPoints = [];
    let downloadDots = "";
    let uploadDots = "";
    let hoverAreas = "";

    points.forEach(point => {
        const x = xForHour(point.hour);
        const yd = yForValue(point.download);
        const yu = yForValue(point.upload);

        downloadPoints.push(`${x},${yd}`);
        uploadPoints.push(`${x},${yu}`);

        downloadDots += `<circle cx="${x}" cy="${yd}" r="3.5" class="chart-download-point" />`;
        uploadDots += `<circle cx="${x}" cy="${yu}" r="3.5" class="chart-upload-point" />`;

        hoverAreas += `
            <rect x="${x - 18}" y="${paddingTop}" width="36" height="${graphHeight}"
                  class="chart-hover-area"
                  data-hour="${point.hour}"
                  data-download="${point.download}"
                  data-upload="${point.upload}" />
        `;
    });

    box.innerHTML = `
        <div class="chart-tooltip" id="hourlyTooltip">
            <div class="tooltip-hour">--:--</div>
            <div class="tooltip-row">
                <span class="tooltip-dot download"></span>
                <span>DOWNLOAD</span>
                <strong class="tooltip-download">0 B</strong>
            </div>
            <div class="tooltip-row">
                <span class="tooltip-dot upload"></span>
                <span>UPLOAD</span>
                <strong class="tooltip-upload">0 B</strong>
            </div>
            <div class="tooltip-row tooltip-total">
                <span></span>
                <span>TOTAL</span>
                <strong class="tooltip-total-value">0 B</strong>
            </div>
        </div>

        <svg viewBox="0 0 ${width} ${height}" class="usage-chart" preserveAspectRatio="none" aria-label="Hourly network usage chart">
            ${grid}
            <polyline points="${downloadPoints.join(" ")}" class="chart-download" fill="none" />
            <polyline points="${uploadPoints.join(" ")}" class="chart-upload" fill="none" />
            ${downloadDots}
            ${uploadDots}
            <line id="chartGuide" x1="0" y1="${paddingTop}" x2="0" y2="${paddingTop + graphHeight}" class="chart-guide" />
            ${hoverAreas}
            ${xLabels}
        </svg>
    `;

    const tooltip = box.querySelector("#hourlyTooltip");
    const guide = box.querySelector("#chartGuide");
    const areas = box.querySelectorAll(".chart-hover-area");

    function showTooltip(area) {
        if (!tooltip) return;
        const hour = Number(area.dataset.hour || 0);
        const download = Number(area.dataset.download || 0);
        const upload = Number(area.dataset.upload || 0);
        const total = download + upload;

        const hourText = `${String(hour).padStart(2, "0")}:00`;
        tooltip.querySelector(".tooltip-hour").textContent = `${ist.month}/${ist.day} · ${hourText}`;
        tooltip.querySelector(".tooltip-download").textContent = formatBytes(download);
        tooltip.querySelector(".tooltip-upload").textContent = formatBytes(upload);
        tooltip.querySelector(".tooltip-total-value").textContent = formatBytes(total);

        if (guide) {
            const x = xForHour(hour);
            guide.setAttribute("x1", x);
            guide.setAttribute("x2", x);
            guide.classList.add("active");
        }

        const boxRect = box.getBoundingClientRect();
        const x = xForHour(hour);
        const scaleX = boxRect.width / width;

        let left = x * scaleX + 14;
        let top = 22;
        const tooltipWidth = tooltip.offsetWidth || 210;
        const tooltipHeight = tooltip.offsetHeight || 120;

        if (left + tooltipWidth > boxRect.width - 10) {
            left = x * scaleX - tooltipWidth - 14;
        }
        if (left < 10) left = 10;
        if (top + tooltipHeight > boxRect.height - 10) {
            top = boxRect.height - tooltipHeight - 10;
        }

        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
        tooltip.classList.add("visible");
    }

    function hideTooltip() {
        if (tooltip) tooltip.classList.remove("visible");
        if (guide) guide.classList.remove("active");
    }

    areas.forEach(area => {
        area.addEventListener("mouseenter", () => showTooltip(area));
        area.addEventListener("mousemove", () => showTooltip(area));
        area.addEventListener("mouseleave", hideTooltip);
    });
}

// ============================================================
// Daily History & Overview Daily Chart (Last 7 Days)
// ============================================================

function getLastSevenDates() {
    const now = new Date();
    const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: IST_TIMEZONE,
        year: "numeric",
        month: "2-digit",
        day: "2-digit"
    }).formatToParts(now);

    const values = {};
    parts.forEach(p => {
        if (p.type !== "literal") values[p.type] = Number(p.value);
    });

    const base = new Date(Date.UTC(values.year, values.month - 1, values.day));
    const formatter = new Intl.DateTimeFormat("en-CA", {
        timeZone: IST_TIMEZONE,
        year: "numeric",
        month: "2-digit",
        day: "2-digit"
    });

    const result = [];
    for (let i = 6; i >= 0; i--) {
        const d = new Date(base);
        d.setUTCDate(base.getUTCDate() - i);
        result.push(formatter.format(d));
    }
    return result;
}

async function loadDailyHistory() {
    try {
        const data = await getJSON("/usage/daily");
        dailyHistory = data.days || data.history || [];
        renderDailyChart();
        renderDailyHistory();
    } catch (err) {
        console.error("Daily history error:", err);
    }
}

function renderDailyChart() {
    const panel = $("overviewDailyUsage");
    if (!panel) return;

    const historyMap = {};
    (dailyHistory || []).forEach(item => {
        const d = item.date || item.day;
        if (d) {
            const key = String(d).substring(0, 10);
            historyMap[key] = {
                download: Number(item.download_bytes || 0),
                upload: Number(item.upload_bytes || 0),
                total: Number(item.total_bytes || (Number(item.download_bytes || 0) + Number(item.upload_bytes || 0)))
            };
        }
    });

    const dates = getLastSevenDates();
    const days = dates.map(date => {
        const item = historyMap[date] || { download: 0, upload: 0, total: 0 };
        return { date, download: item.download, upload: item.upload, total: item.total };
    });

    const maxTotal = Math.max(...days.map(d => d.total), 1);
    const bars = days.map(item => {
        const height = item.total > 0 ? Math.max(4, (item.total / maxTotal) * 140) : 4;
        const dlHeight = item.total > 0 ? (item.download / item.total) * height : 0;
        const ulHeight = item.total > 0 ? (item.upload / item.total) * height : 0;
        const label = item.date.substring(8); // day of month

        return `
            <div class="daily-bar-group">
                <div class="daily-bar" style="height:${height}px" title="${escapeHtml(item.date)} — ${escapeHtml(formatBytes(item.total))}">
                    <div class="daily-download" style="height:${dlHeight}px"></div>
                    <div class="daily-upload" style="height:${ulHeight}px"></div>
                </div>
                <span>${escapeHtml(label)}</span>
            </div>
        `;
    }).join("");

    const totalDownload = days.reduce((sum, d) => sum + d.download, 0);
    const totalUpload = days.reduce((sum, d) => sum + d.upload, 0);

    panel.innerHTML = `
        <h3>
            DAILY USAGE
            <small>(LAST 7 DAYS)</small>
        </h3>
        <div class="daily-chart">
            ${bars}
        </div>
        <div class="daily-summary">
            <span>
                <i class="orange-dot"></i>
                DOWNLOAD
                <strong>${formatBytes(totalDownload)}</strong>
            </span>
            <span>
                <i class="teal-dot"></i>
                UPLOAD
                <strong>${formatBytes(totalUpload)}</strong>
            </span>
        </div>
    `;
}

function renderDailyHistory() {
    const container = $("historyList");
    if (!container) return;

    if (!dailyHistory.length) {
        container.innerHTML = `<div class="pending">No daily history available.</div>`;
        return;
    }

    const recent = [...dailyHistory].slice(-30).reverse();
    container.innerHTML = recent.map(day => `
        <div class="history-row">
            <span><strong>${escapeHtml(day.date || day.day)}</strong></span>
            <span class="orange">↓ ${escapeHtml(formatBytes(day.download_bytes || 0))}</span>
            <span class="teal">↑ ${escapeHtml(formatBytes(day.upload_bytes || 0))}</span>
            <strong>${escapeHtml(formatBytes(day.total_bytes || 0))}</strong>
        </div>
    `).join("");
}

// ============================================================
// Network Statistics
// ============================================================

async function loadNetworkStats() {
    try {
        const data = await getJSON("/network/stats");
        networkStats = data.stats || data || null;
        renderNetworkStats();
    } catch (err) {
        console.error("Network stats error:", err);
    }
}

function renderNetworkStats() {
    const panel = $("overviewNetworkStats");
    if (panel && networkStats) {
        panel.innerHTML = `
            <h3>NETWORK STATISTICS</h3>
            <div class="stats-grid">
                <div><span>PACKETS RECEIVED</span><strong>${formatNumber(networkStats.packets_rx)}</strong></div>
                <div><span>PACKETS TRANSMITTED</span><strong>${formatNumber(networkStats.packets_tx)}</strong></div>
                <div><span>RX DROPPED</span><strong>${formatNumber(networkStats.dropped_rx)}</strong></div>
                <div><span>TX DROPPED</span><strong>${formatNumber(networkStats.dropped_tx)}</strong></div>
                <div><span>RX ERRORS</span><strong>${formatNumber(networkStats.errors_rx)}</strong></div>
                <div><span>TX ERRORS</span><strong>${formatNumber(networkStats.errors_tx)}</strong></div>
                <div><span>RX BYTES</span><strong>${formatBytes(networkStats.bytes_rx)}</strong></div>
                <div><span>TX BYTES</span><strong>${formatBytes(networkStats.bytes_tx)}</strong></div>
            </div>
        `;
    }

    const netGrid = $("networkTelemetryGrid");
    if (netGrid && networkStats) {
        netGrid.innerHTML = `
            <div class="stats-grid">
                <div><span>TOTAL DOWNLOAD</span><strong class="orange">${formatBytes(networkStats.download_bytes || 0)}</strong></div>
                <div><span>TOTAL UPLOAD</span><strong class="teal">${formatBytes(networkStats.upload_bytes || 0)}</strong></div>
                <div><span>PACKETS RECEIVED</span><strong>${formatNumber(networkStats.packets_rx)}</strong></div>
                <div><span>PACKETS TRANSMITTED</span><strong>${formatNumber(networkStats.packets_tx)}</strong></div>
                <div><span>RX DROPPED</span><strong>${formatNumber(networkStats.dropped_rx)}</strong></div>
                <div><span>TX DROPPED</span><strong>${formatNumber(networkStats.dropped_tx)}</strong></div>
                <div><span>RX ERRORS</span><strong>${formatNumber(networkStats.errors_rx)}</strong></div>
                <div><span>TX ERRORS</span><strong>${formatNumber(networkStats.errors_tx)}</strong></div>
                <div><span>RX BYTES</span><strong>${formatBytes(networkStats.bytes_rx)}</strong></div>
                <div><span>TX BYTES</span><strong>${formatBytes(networkStats.bytes_tx)}</strong></div>
            </div>
        `;
    }
}

// ============================================================
// Device Details View
// ============================================================

async function openDevice(mac) {
    if (!mac) return;
    selectedDevice = mac;

    switchView("device-details");

    const fields = [
        "deviceDetailTitle", "deviceDetailHostname", "deviceDetailIP", "deviceDetailMac",
        "deviceTodayTotal", "deviceTodayDownload", "deviceTodayUpload",
        "deviceYesterdayTotal", "deviceYesterdayDownload", "deviceYesterdayUpload",
        "deviceSevenDayTotal", "deviceSevenDayDownload", "deviceSevenDayUpload",
        "deviceMonthTotal", "deviceMonthDownload", "deviceMonthUpload",
        "detailHostname", "detailIPv4", "detailIPv6", "detailMac", "detailRadio", "detailSSID", "detailAP",
        "detailTimeConnected", "detailFirstSeen", "detailLastSeen",
        "detailPacketsRx", "detailPacketsTx", "detailDroppedRx", "detailDroppedTx",
        "detailErrorsRx", "detailErrorsTx", "detailBytesRx", "detailBytesTx"
    ];
    fields.forEach(id => setText(id, "--"));

    if ($("deviceDailyChart")) {
        $("deviceDailyChart").innerHTML = `<div class="pending">LOADING DEVICE DATA...</div>`;
    }

    try {
        const encodedMac = encodeURIComponent(mac);
        const [devRes, dailyRes, statsRes] = await Promise.all([
            getJSON(`/devices/${encodedMac}`).catch(() => null),
            getJSON(`/devices/${encodedMac}/daily`).catch(() => null),
            getJSON(`/devices/${encodedMac}/stats`).catch(() => null)
        ]);

        const device = devRes?.device || devRes || {};
        const usage = devRes?.usage || {};
        const daily = dailyRes?.days || dailyRes?.history || [];
        const stats = statsRes?.stats || statsRes || {};

        const hostname = device.hostname || "Device Details";
        setText("deviceDetailTitle", hostname);
        setText("deviceDetailHostname", hostname);
        setText("deviceDetailIP", device.ip_address || device.ipv4_address || "--");
        setText("deviceDetailMac", device.mac_address || mac);

        if ($("deviceDetailStatus")) {
            $("deviceDetailStatus").className = `status-dot ${device.is_active ? '' : 'offline'}`;
        }

        // 4 Period Usage Cards
        const t = usage.today || {};
        const y = usage.yesterday || {};
        const w = usage.last_7_days || {};
        const m = usage.this_month || {};

        setText("deviceTodayTotal", formatBytes(t.total_bytes || 0));
        setText("deviceTodayDownload", formatBytes(t.download_bytes || 0));
        setText("deviceTodayUpload", formatBytes(t.upload_bytes || 0));

        setText("deviceYesterdayTotal", formatBytes(y.total_bytes || 0));
        setText("deviceYesterdayDownload", formatBytes(y.download_bytes || 0));
        setText("deviceYesterdayUpload", formatBytes(y.upload_bytes || 0));

        setText("deviceSevenDayTotal", formatBytes(w.total_bytes || 0));
        setText("deviceSevenDayDownload", formatBytes(w.download_bytes || 0));
        setText("deviceSevenDayUpload", formatBytes(w.upload_bytes || 0));

        setText("deviceMonthTotal", formatBytes(m.total_bytes || 0));
        setText("deviceMonthDownload", formatBytes(m.download_bytes || 0));
        setText("deviceMonthUpload", formatBytes(m.upload_bytes || 0));

        // Device Information
        setText("detailHostname", device.hostname || "--");
        setText("detailIPv4", device.ip_address || device.ipv4_address || "--");
        setText("detailIPv6", device.ipv6_address || "--");
        setText("detailMac", device.mac_address || mac);
        setText("detailRadio", device.radio || "--");
        setText("detailSSID", device.ssid || "--");
        setText("detailAP", device.ap || device.ap_name || "--");
        setText("detailTimeConnected", device.time_connected || "--");
        setText("detailFirstSeen", formatDateTime(device.first_seen));
        setText("detailLastSeen", formatDateTime(device.last_seen));

        // Device Statistics
        setText("detailPacketsRx", formatNumber(stats.packets_rx));
        setText("detailPacketsTx", formatNumber(stats.packets_tx));
        setText("detailDroppedRx", formatNumber(stats.dropped_rx));
        setText("detailDroppedTx", formatNumber(stats.dropped_tx));
        setText("detailErrorsRx", formatNumber(stats.errors_rx));
        setText("detailErrorsTx", formatNumber(stats.errors_tx));
        setText("detailBytesRx", formatBytes(stats.bytes_rx));
        setText("detailBytesTx", formatBytes(stats.bytes_tx));

        // Device Daily Chart (Last 7 Days)
        renderDeviceDailyChart(daily);

    } catch (err) {
        console.error("Open device error:", err);
        if ($("deviceDailyChart")) {
            $("deviceDailyChart").innerHTML = `<div class="pending">DEVICE DATA UNAVAILABLE</div>`;
        }
    }
}

function renderDeviceDailyChart(history) {
    const container = $("deviceDailyChart");
    if (!container) return;

    const historyMap = {};
    (history || []).forEach(item => {
        const d = item.date || item.day;
        if (d) {
            const key = String(d).substring(0, 10);
            historyMap[key] = {
                download: Number(item.download_bytes || 0),
                upload: Number(item.upload_bytes || 0),
                total: Number(item.total_bytes || (Number(item.download_bytes || 0) + Number(item.upload_bytes || 0)))
            };
        }
    });

    const dates = getLastSevenDates();
    const days = dates.map(date => {
        const item = historyMap[date] || { download: 0, upload: 0, total: 0 };
        return { date, download: item.download, upload: item.upload, total: item.total };
    });

    const maxTotal = Math.max(...days.map(d => d.total), 1);
    const bars = days.map(item => {
        const totalHeight = item.total > 0 ? Math.max(5, (item.total / maxTotal) * 190) : 4;
        const dlHeight = item.total > 0 ? (item.download / item.total) * totalHeight : 0;
        const ulHeight = item.total > 0 ? (item.upload / item.total) * totalHeight : 0;
        const label = item.date.substring(5);

        return `
            <div class="device-day">
                <span class="device-day-value">${escapeHtml(formatBytes(item.total))}</span>
                <div class="device-day-bar" style="height:${totalHeight}px" title="${escapeHtml(item.date)} — ${escapeHtml(formatBytes(item.total))}">
                    <div class="device-day-download" style="height:${dlHeight}px"></div>
                    <div class="device-day-upload" style="height:${ulHeight}px"></div>
                </div>
                <span class="device-day-label">${escapeHtml(label)}</span>
            </div>
        `;
    }).join("");

    const downloadTotal = days.reduce((sum, d) => sum + d.download, 0);
    const uploadTotal = days.reduce((sum, d) => sum + d.upload, 0);

    container.innerHTML = `
        <div class="device-chart-area">
            <div class="device-chart-bars">
                ${bars}
            </div>
            <div class="device-chart-summary">
                <span>
                    <i class="orange-dot"></i>
                    DOWNLOAD
                    <strong>${formatBytes(downloadTotal)}</strong>
                </span>
                <span>
                    <i class="teal-dot"></i>
                    UPLOAD
                    <strong>${formatBytes(uploadTotal)}</strong>
                </span>
            </div>
        </div>
    `;
}

// ============================================================
// Navigation
// ============================================================

function switchView(viewName) {
    if (!viewName) return;
    currentView = viewName;

    document.querySelectorAll(".nav").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.view === viewName);
    });

    document.querySelectorAll(".view").forEach(sec => {
        sec.classList.toggle("active", sec.id === viewName);
    });

    if (viewName === "history") loadDailyHistory();
    if (viewName === "network") loadNetworkStats();
    if (viewName === "devices") loadDevices();
}

function initNavigation() {
    document.querySelectorAll(".nav").forEach(btn => {
        btn.addEventListener("click", () => {
            switchView(btn.dataset.view);
        });
    });

    const refreshBtn = $("refresh");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", async () => {
            refreshBtn.classList.add("refreshing");
            refreshBtn.disabled = true;
            await refreshAll();
            setTimeout(() => {
                refreshBtn.classList.remove("refreshing");
                refreshBtn.disabled = false;
            }, 600);
        });
    }

    const deviceBackBtn = $("deviceBack");
    if (deviceBackBtn) {
        deviceBackBtn.addEventListener("click", () => {
            switchView("devices");
            selectedDevice = null;
        });
    }

    const viewAllBtn = document.querySelector(".panel.devices button[data-view='devices']");
    if (viewAllBtn) {
        viewAllBtn.addEventListener("click", () => {
            switchView("devices");
        });
    }
}

// ============================================================
// Main Refresh Cycle
// ============================================================

async function refreshAll() {
    await Promise.allSettled([
        loadStatus(),
        loadTodayUsage(),
        loadHourlyUsage(),
        loadDevices(),
        loadDailyHistory(),
        loadNetworkStats()
    ]);

    if (selectedDevice && currentView === "device-details") {
        openDevice(selectedDevice);
    }
}

// ============================================================
// Bootstrap
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    updateClock();
    setInterval(updateClock, 1000);
    refreshAll();
    setInterval(refreshAll, 15000);
});
