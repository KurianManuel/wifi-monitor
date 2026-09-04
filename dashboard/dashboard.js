/**
 * Jio WiFi Data Tracker - Modular Dashboard Client Script
 * 
 * Target: Raspberry Pi Zero 2 W & Modern Web Browsers
 * Architecture: Vanilla JS, Event-driven, Component-isolated error handling
 */

// Strict API base path as specified
const API = "/api";

// Deterministic palette for device distribution
const DEVICE_COLORS = [
  "#F06021", // Orange (Primary)
  "#6B9CAA", // Teal / Moonstone
  "#7E8CE0", // Lavender Blue
  "#C17BDE", // Purple / Orchid
  "#5FAF8F", // Sage Green
  "#D4A84F", // Amber Gold
  "#D66A8A", // Rose
  "#7FA8C9", // Soft Cyan
  "#E08543", // Warm Orange
  "#4CA6A4"  // Dark Mint
];

/**
 * Format bytes to readable units: B, KB, MB, GB, TB
 */
function formatBytes(bytes, decimals = 2) {
  if (bytes === undefined || bytes === null || isNaN(bytes)) return "0 B";
  const b = Number(bytes);
  if (b === 0) return "0 B";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["B", "KB", "MB", "GB", "TB", "PB"];
  const i = Math.floor(Math.log(Math.abs(b)) / Math.log(k));
  const safeI = Math.min(i, sizes.length - 1);
  return parseFloat((b / Math.pow(k, safeI)).toFixed(dm)) + " " + sizes[safeI];
}

/**
 * Format integers with standard locale grouping
 */
function formatNumber(num) {
  if (num === undefined || num === null || isNaN(num)) return "0";
  return Number(num).toLocaleString();
}

/**
 * Deterministic color assignment based on MAC or Device name
 */
function getDeviceColor(identifier) {
  if (!identifier) return DEVICE_COLORS[0];
  let hash = 0;
  for (let i = 0; i < identifier.length; i++) {
    hash = identifier.charCodeAt(i) + ((hash << 5) - hash);
  }
  const index = Math.abs(hash) % DEVICE_COLORS.length;
  return DEVICE_COLORS[index];
}

/**
 * Fetch helper wrapping fetch with error handling and no-cache
 */
async function getJSON(path) {
  const url = `${API}${path}`;
  try {
    const res = await fetch(url, {
      headers: { "Accept": "application/json" },
      cache: "no-store"
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} from ${url}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`Fetch error for ${url}:`, err);
    throw err;
  }
}

/**
 * Live IST Clock updater
 */
function updateISTClock() {
  const clockEl = document.getElementById("currentClock");
  if (!clockEl) return;
  
  try {
    const now = new Date();
    // Format to Asia/Kolkata
    const options = {
      timeZone: "Asia/Kolkata",
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    };
    const timeStr = new Intl.DateTimeFormat("en-GB", options).format(now);
    clockEl.textContent = `${timeStr} IST`;
  } catch (e) {
    clockEl.textContent = new Date().toLocaleTimeString();
  }
}

/**
 * Load System Status
 */
async function loadStatus() {
  try {
    const data = await getJSON("/status");
    const routerIdentity = document.getElementById("routerIdentity");
    const statusDot = document.getElementById("statusDot");
    const connectionStatus = document.getElementById("connectionStatus");
    const infoRouterModel = document.getElementById("infoRouterModel");
    const infoRouterHost = document.getElementById("infoRouterHost");
    const infoOperatingMode = document.getElementById("infoOperatingMode");
    const footerMode = document.getElementById("footerModeStatus");

    if (routerIdentity) routerIdentity.textContent = data.router?.identity || "Jio Router";
    if (infoRouterModel) infoRouterModel.textContent = data.router?.identity || "JioFiber";
    if (infoRouterHost) infoRouterHost.textContent = data.router?.host || "192.168.29.1";
    if (infoOperatingMode) infoOperatingMode.textContent = (data.router?.mode || "MOCK").toUpperCase();
    if (footerMode) footerMode.textContent = `Mode: ${(data.router?.mode || "MOCK").toUpperCase()}`;

    if (data.router?.connected) {
      if (statusDot) statusDot.className = "pulse-dot";
      if (connectionStatus) connectionStatus.textContent = "CONNECTED";
    } else {
      if (statusDot) statusDot.className = "pulse-dot disconnected";
      if (connectionStatus) connectionStatus.textContent = "DISCONNECTED";
    }

    const lastUpdated = document.getElementById("lastUpdated");
    if (lastUpdated) {
      const now = new Date();
      lastUpdated.textContent = now.toLocaleTimeString();
    }
  } catch (err) {
    const statusDot = document.getElementById("statusDot");
    const connectionStatus = document.getElementById("connectionStatus");
    if (statusDot) statusDot.className = "pulse-dot disconnected";
    if (connectionStatus) connectionStatus.textContent = "API OFFLINE";
  }
}

/**
 * Load and Render Today's Overall Usage
 */
async function loadTodayUsage() {
  try {
    const data = await getJSON("/usage/today");
    const valTotalToday = document.getElementById("valTotalToday");
    const valDownloadToday = document.getElementById("valDownloadToday");
    const valUploadToday = document.getElementById("valUploadToday");

    if (valTotalToday) valTotalToday.textContent = formatBytes(data.total_bytes);
    if (valDownloadToday) valDownloadToday.textContent = formatBytes(data.download_bytes);
    if (valUploadToday) valUploadToday.textContent = formatBytes(data.upload_bytes);
  } catch (err) {
    const valTotalToday = document.getElementById("valTotalToday");
    if (valTotalToday) valTotalToday.textContent = "Unavailable";
  }
}

/**
 * Load and Render 24-Hour Timeline Chart
 */
async function loadHourlyUsage() {
  const container = document.getElementById("hourlyChart");
  if (!container) return;

  try {
    const data = await getJSON("/usage/hourly");
    renderHourlyChart(data.hours || []);
  } catch (err) {
    container.innerHTML = `<p class="placeholder-text" style="color: var(--color-danger);">HOURLY DATA UNAVAILABLE</p>`;
  }
}

/**
 * Render 24-Hour SVG bar/area chart
 */
function renderHourlyChart(hours) {
  const container = document.getElementById("hourlyChart");
  if (!container) return;

  if (!hours || hours.length === 0) {
    container.innerHTML = `<p class="placeholder-text">No hourly traffic recorded yet today.</p>`;
    return;
  }

  // Find max value for scaling
  let maxBytes = 1;
  hours.forEach(h => {
    if (h.total_bytes > maxBytes) maxBytes = h.total_bytes;
  });

  const width = 600;
  const height = 200;
  const paddingLeft = 45;
  const paddingBottom = 25;
  const paddingTop = 15;
  const paddingRight = 15;

  const chartW = width - paddingLeft - paddingRight;
  const chartH = height - paddingTop - paddingBottom;
  const barWidth = Math.max(2, (chartW / 24) - 4);

  let barsSvg = "";
  let xLabels = "";

  hours.forEach((item, index) => {
    const x = paddingLeft + (index * (chartW / 24)) + 2;
    const dlHeight = (item.download_bytes / maxBytes) * chartH;
    const ulHeight = (item.upload_bytes / maxBytes) * chartH;

    const yDl = paddingTop + chartH - dlHeight;
    const yUl = yDl - ulHeight;

    barsSvg += `
      <g class="chart-hour-bar" data-hour="${item.hour}" data-dl="${item.download_bytes}" data-ul="${item.upload_bytes}">
        <title>${item.hour} - Down: ${formatBytes(item.download_bytes)}, Up: ${formatBytes(item.upload_bytes)}</title>
        <!-- Download (Orange) -->
        <rect x="${x}" y="${yDl}" width="${barWidth}" height="${dlHeight}" fill="#F06021" rx="1" />
        <!-- Upload (Teal) stacked on top -->
        <rect x="${x}" y="${yUl}" width="${barWidth}" height="${ulHeight}" fill="#6B9CAA" rx="1" />
      </g>
    `;

    // Render every 4th label to prevent clutter
    if (index % 4 === 0 || index === 23) {
      xLabels += `<text x="${x + (barWidth/2)}" y="${height - 6}" font-size="9" fill="#8b949e" text-anchor="middle" font-family="monospace">${item.hour.substring(0, 2)}</text>`;
    }
  });

  // Simple horizontal grid lines
  const gridLines = `
    <line x1="${paddingLeft}" y1="${paddingTop}" x2="${width - paddingRight}" y2="${paddingTop}" stroke="#2a2f38" stroke-dasharray="3,3" />
    <line x1="${paddingLeft}" y1="${paddingTop + chartH/2}" x2="${width - paddingRight}" y2="${paddingTop + chartH/2}" stroke="#2a2f38" stroke-dasharray="3,3" />
    <line x1="${paddingLeft}" y1="${paddingTop + chartH}" x2="${width - paddingRight}" y2="${paddingTop + chartH}" stroke="#4D4D4D" />
    <text x="${paddingLeft - 6}" y="${paddingTop + 4}" font-size="8" fill="#8b949e" text-anchor="end" font-family="monospace">${formatBytes(maxBytes, 0)}</text>
    <text x="${paddingLeft - 6}" y="${paddingTop + chartH}" font-size="8" fill="#8b949e" text-anchor="end" font-family="monospace">0</text>
  `;

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg" preserveAspectRatio="none">
      ${gridLines}
      ${barsSvg}
      ${xLabels}
    </svg>
  `;
}

/**
 * Load and Render Connected Devices
 */
async function loadDevices() {
  try {
    const data = await getJSON("/devices");
    const devices = data.devices || [];

    // Update active count
    const activeCountEl = document.getElementById("valActiveDevices");
    if (activeCountEl) activeCountEl.textContent = devices.filter(d => d.is_active).length || devices.length;

    renderDevices(devices);
    renderDistribution(devices);
  } catch (err) {
    const overviewBody = document.getElementById("overviewDevicesBody");
    if (overviewBody) {
      overviewBody.innerHTML = `<tr><td colspan="7" class="table-empty" style="color: var(--color-danger);">DEVICES DATA UNAVAILABLE</td></tr>`;
    }
  }
}

/**
 * Render Devices in Overview Table and Full Devices Table
 */
function renderDevices(devices) {
  const overviewBody = document.getElementById("overviewDevicesBody");
  const fullBody = document.getElementById("fullDevicesBody");

  if (!devices || devices.length === 0) {
    if (overviewBody) overviewBody.innerHTML = `<tr><td colspan="7" class="table-empty">No devices active or registered yet.</td></tr>`;
    if (fullBody) fullBody.innerHTML = `<tr><td colspan="8" class="table-empty">No devices discovered.</td></tr>`;
    return;
  }

  // Render top 5 in Overview
  if (overviewBody) {
    const topDevices = devices.slice(0, 6);
    overviewBody.innerHTML = topDevices.map(dev => `
      <tr class="clickable" onclick="openDevice('${dev.mac_address}')" title="Click to view details">
        <td><strong>${dev.hostname || "Device"}</strong><br><small style="color:var(--color-text-muted);">${dev.mac_address}</small></td>
        <td>${dev.ip_address || "--"}</td>
        <td style="color:var(--color-orange);">${formatBytes(dev.download_bytes)}</td>
        <td style="color:var(--color-teal);">${formatBytes(dev.upload_bytes)}</td>
        <td><strong>${formatBytes(dev.total_bytes)}</strong></td>
        <td>${dev.last_seen ? new Date(dev.last_seen).toLocaleTimeString() : "--"}</td>
        <td><span class="badge-pill ${dev.is_active ? 'active' : 'inactive'}">${dev.is_active ? 'ONLINE' : 'IDLE'}</span></td>
      </tr>
    `).join("");
  }

  // Render all in Devices tab
  if (fullBody) {
    fullBody.innerHTML = devices.map(dev => `
      <tr class="clickable" onclick="openDevice('${dev.mac_address}')">
        <td><strong>${dev.hostname || "Device"}</strong></td>
        <td><code>${dev.mac_address}</code></td>
        <td>${dev.ip_address || "--"}</td>
        <td>${dev.radio || "--"}</td>
        <td>${dev.ssid || "--"}</td>
        <td>${dev.ap || "--"}</td>
        <td>${dev.last_seen ? new Date(dev.last_seen).toLocaleString() : "--"}</td>
        <td><span class="badge-pill ${dev.is_active ? 'active' : 'inactive'}">${dev.is_active ? 'ONLINE' : 'IDLE'}</span></td>
      </tr>
    `).join("");
  }
}

/**
 * Render Usage Distribution Donut Chart
 */
function renderDistribution(devices) {
  const container = document.getElementById("distribution");
  if (!container) return;

  const activeWithUsage = devices.filter(d => (d.total_bytes || 0) > 0);
  if (!activeWithUsage.length) {
    container.innerHTML = `<p class="placeholder-text">No traffic usage recorded to distribute.</p>`;
    return;
  }

  const grandTotal = activeWithUsage.reduce((sum, d) => sum + (d.total_bytes || 0), 0);
  let cumulativePercent = 0;
  const segments = [];

  activeWithUsage.forEach(dev => {
    const percent = ((dev.total_bytes || 0) / grandTotal) * 100;
    const color = getDeviceColor(dev.mac_address);
    segments.push({
      mac: dev.mac_address,
      name: dev.hostname || dev.mac_address.substring(dev.mac_address.length - 8),
      bytes: dev.total_bytes,
      percent: percent,
      color: color,
      offset: cumulativePercent
    });
    cumulativePercent += percent;
  });

  // SVG Donut with stroke-dasharray (circumference = 2 * PI * 40 = ~251.3)
  const C = 251.327;
  let circlesSvg = "";
  let legendItems = "";

  segments.forEach(seg => {
    const strokeDash = (seg.percent / 100) * C;
    const strokeOffset = -(seg.offset / 100) * C;
    circlesSvg += `
      <circle r="40" cx="50" cy="50" fill="transparent"
        stroke="${seg.color}"
        stroke-width="15"
        stroke-dasharray="${strokeDash} ${C - strokeDash}"
        stroke-dashoffset="${strokeOffset}"
      >
        <title>${seg.name}: ${seg.percent.toFixed(1)}% (${formatBytes(seg.bytes)})</title>
      </circle>
    `;

    legendItems += `
      <div class="donut-legend-item">
        <span class="donut-color-swatch" style="background-color: ${seg.color}"></span>
        <span style="color: #fff;">${seg.name}</span>
        <span style="color: var(--color-text-muted); margin-left: auto;">${formatBytes(seg.bytes)} (${seg.percent.toFixed(1)}%)</span>
      </div>
    `;
  });

  container.innerHTML = `
    <div class="donut-wrapper">
      <div class="donut-svg-container">
        <svg viewBox="0 0 100 100" style="transform: rotate(-90deg); width: 100%; height: 100%;">
          ${circlesSvg}
        </svg>
      </div>
      <div class="donut-legend-list">
        ${legendItems}
      </div>
    </div>
  `;
}

/**
 * Load and Render Network Level Telemetry & Counters
 */
async function loadNetworkStats() {
  try {
    const stats = await getJSON("/network/stats");
    
    // Mini stats container
    const rxB = document.getElementById("netRxBytes");
    const txB = document.getElementById("netTxBytes");
    const rxP = document.getElementById("netRxPkts");
    const txP = document.getElementById("netTxPkts");
    const rxE = document.getElementById("netRxErrors");
    const txE = document.getElementById("netTxErrors");
    const rxD = document.getElementById("netRxDropped");
    const txD = document.getElementById("netTxDropped");

    if (rxB) rxB.textContent = formatBytes(stats.bytes_rx);
    if (txB) txB.textContent = formatBytes(stats.bytes_tx);
    if (rxP) rxP.textContent = formatNumber(stats.packets_rx);
    if (txP) txP.textContent = formatNumber(stats.packets_tx);
    if (rxE) rxE.textContent = formatNumber(stats.errors_rx);
    if (txE) txE.textContent = formatNumber(stats.errors_tx);
    if (rxD) rxD.textContent = formatNumber(stats.dropped_rx);
    if (txD) txD.textContent = formatNumber(stats.dropped_tx);

    // Full Network Tab stats
    const netFullDl = document.getElementById("netFullDownload");
    const netFullUl = document.getElementById("netFullUpload");
    const netFullRxP = document.getElementById("netFullRxPkts");
    const netFullTxP = document.getElementById("netFullTxPkts");
    const netFullRxE = document.getElementById("netFullRxErrors");
    const netFullTxE = document.getElementById("netFullTxErrors");
    const netFullRxD = document.getElementById("netFullRxDropped");
    const netFullTxD = document.getElementById("netFullTxDropped");

    if (netFullDl) netFullDl.textContent = formatBytes(stats.download_bytes);
    if (netFullUl) netFullUl.textContent = formatBytes(stats.upload_bytes);
    if (netFullRxP) netFullRxP.textContent = formatNumber(stats.packets_rx);
    if (netFullTxP) netFullTxP.textContent = formatNumber(stats.packets_tx);
    if (netFullRxE) netFullRxE.textContent = formatNumber(stats.errors_rx);
    if (netFullTxE) netFullTxE.textContent = formatNumber(stats.errors_tx);
    if (netFullRxD) netFullRxD.textContent = formatNumber(stats.dropped_rx);
    if (netFullTxD) netFullTxD.textContent = formatNumber(stats.dropped_tx);
  } catch (err) {
    const netStats = document.getElementById("networkStats");
    if (netStats) {
      netStats.innerHTML = `<p class="placeholder-text" style="color: var(--color-danger);">NETWORK STATISTICS UNAVAILABLE</p>`;
    }
  }
}

/**
 * Load Historical Usage (Today, Yesterday, 7 Days, This Month)
 */
async function loadUsageHistory() {
  try {
    const [today, yest, week, month, daily] = await Promise.all([
      getJSON("/usage/today").catch(() => null),
      getJSON("/usage/yesterday").catch(() => null),
      getJSON("/usage/7days").catch(() => null),
      getJSON("/usage/month").catch(() => null),
      getJSON("/usage/daily").catch(() => null)
    ]);

    if (today) {
      const el = document.getElementById("histTodayTotal");
      const sub = document.getElementById("histTodaySub");
      if (el) el.textContent = formatBytes(today.total_bytes);
      if (sub) sub.textContent = `↓ ${formatBytes(today.download_bytes)}  ↑ ${formatBytes(today.upload_bytes)}`;
    }

    if (yest) {
      const el = document.getElementById("histYesterdayTotal");
      const sub = document.getElementById("histYesterdaySub");
      if (el) el.textContent = formatBytes(yest.total_bytes);
      if (sub) sub.textContent = `↓ ${formatBytes(yest.download_bytes)}  ↑ ${formatBytes(yest.upload_bytes)}`;
    }

    if (week) {
      const el = document.getElementById("hist7DaysTotal");
      const sub = document.getElementById("hist7DaysSub");
      if (el) el.textContent = formatBytes(week.total_bytes);
      if (sub) sub.textContent = `↓ ${formatBytes(week.download_bytes)}  ↑ ${formatBytes(week.upload_bytes)}`;
    }

    if (month) {
      const el = document.getElementById("histMonthTotal");
      const sub = document.getElementById("histMonthSub");
      if (el) el.textContent = formatBytes(month.total_bytes);
      if (sub) sub.textContent = `↓ ${formatBytes(month.download_bytes)}  ↑ ${formatBytes(month.upload_bytes)}`;
    }

    // Daily Table
    const dailyBody = document.getElementById("dailyUsageBody");
    if (dailyBody && daily && daily.days) {
      if (daily.days.length === 0) {
        dailyBody.innerHTML = `<tr><td colspan="4" class="table-empty">No daily history recorded yet.</td></tr>`;
      } else {
        dailyBody.innerHTML = daily.days.map(d => `
          <tr>
            <td><strong>${d.day}</strong></td>
            <td style="color:var(--color-orange);">${formatBytes(d.download_bytes)}</td>
            <td style="color:var(--color-teal);">${formatBytes(d.upload_bytes)}</td>
            <td><strong>${formatBytes(d.total_bytes)}</strong></td>
          </tr>
        `).join("");
      }
    }
  } catch (err) {
    console.error("Failed to load usage history:", err);
  }
}

/**
 * Open Device Details modal / view
 */
async function openDevice(mac) {
  const panel = document.getElementById("deviceDetails");
  if (!panel) return;

  // Switch tab to devices if not already there
  const tabBtn = document.getElementById("tab-devices");
  if (tabBtn) tabBtn.click();

  panel.classList.remove("hidden");
  panel.scrollIntoView({ behavior: "smooth" });

  const nameEl = document.getElementById("detailDeviceName");
  const macEl = document.getElementById("detailDeviceMac");
  if (nameEl) nameEl.textContent = "Loading...";
  if (macEl) macEl.textContent = mac;

  try {
    const [dev, daily, stats] = await Promise.all([
      getJSON(`/devices/${mac}`).catch(() => null),
      getJSON(`/devices/${mac}/daily`).catch(() => null),
      getJSON(`/devices/${mac}/stats`).catch(() => null)
    ]);

    if (dev) {
      if (nameEl) nameEl.textContent = dev.hostname || "Device Details";
    }

    // Daily chart for this device
    const chartBox = document.getElementById("deviceDailyChart");
    if (chartBox && daily && daily.days) {
      chartBox.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 0.4rem;">
          ${daily.days.map(d => `
            <div style="display: flex; justify-content: space-between; font-family: monospace; font-size: 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.05); padding: 0.3rem 0;">
              <span>${d.day}</span>
              <span><span style="color:var(--color-orange);">↓ ${formatBytes(d.download_bytes)}</span> | <span style="color:var(--color-teal);">↑ ${formatBytes(d.upload_bytes)}</span></span>
              <strong>${formatBytes(d.total_bytes)}</strong>
            </div>
          `).join("")}
        </div>
      `;
    }

    // Network stats for this device
    if (stats) {
      const rxB = document.getElementById("devStatRxBytes");
      const txB = document.getElementById("devStatTxBytes");
      const rxP = document.getElementById("devStatRxPkts");
      const txP = document.getElementById("devStatTxPkts");
      const rxE = document.getElementById("devStatRxErrors");
      const txE = document.getElementById("devStatTxErrors");
      const rxD = document.getElementById("devStatRxDropped");
      const txD = document.getElementById("devStatTxDropped");

      if (rxB) rxB.textContent = formatBytes(stats.bytes_rx);
      if (txB) txB.textContent = formatBytes(stats.bytes_tx);
      if (rxP) rxP.textContent = formatNumber(stats.packets_rx);
      if (txP) txP.textContent = formatNumber(stats.packets_tx);
      if (rxE) rxE.textContent = formatNumber(stats.errors_rx);
      if (txE) txE.textContent = formatNumber(stats.errors_tx);
      if (rxD) rxD.textContent = formatNumber(stats.dropped_rx);
      if (txD) txD.textContent = formatNumber(stats.dropped_tx);
    }
  } catch (err) {
    console.error("Failed to load device details:", err);
  }
}

/**
 * Initialize Tab Switching
 */
function initTabs() {
  const tabs = document.querySelectorAll(".nav-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const targetId = `pane-${tab.dataset.tab}`;
      
      document.querySelectorAll(".nav-btn").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

      tab.classList.add("active");
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add("active");

      // Load specific tab data when activated
      if (tab.dataset.tab === "usage") {
        loadUsageHistory();
      } else if (tab.dataset.tab === "network") {
        loadNetworkStats();
      }
    });
  });

  const backBtn = document.getElementById("btnBackToDevices");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      const panel = document.getElementById("deviceDetails");
      if (panel) panel.classList.add("hidden");
    });
  }
}

/**
 * Main App Refresh Cycle
 */
async function refreshAll() {
  await Promise.allSettled([
    loadStatus(),
    loadTodayUsage(),
    loadHourlyUsage(),
    loadDevices(),
    loadNetworkStats()
  ]);
}

/**
 * DOM Ready Bootstrap
 */
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  
  // Start clock
  updateISTClock();
  setInterval(updateISTClock, 1000);

  // Initial load
  refreshAll();

  // Periodic monitoring cycle (default 15s)
  setInterval(refreshAll, 15000);
});
