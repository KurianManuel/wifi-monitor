/**
 * Jio WiFi Data Tracker - Modular Dashboard Client Script
 * 
 * Target: Raspberry Pi Zero 2 W & Modern Web Browsers
 * Architecture: Vanilla JS, Component-isolated error handling, Read-Only
 */

// Strict API base path
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

// Global cache for client-side search/filtering
let allDevicesCache = [];
let activeDeviceMac = null;

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
 * Standard GET helper ensuring no double API prefix and cache-control
 */
async function getJSON(path) {
  // Ensure path starts with /
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${API}${cleanPath}`;
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
 * Live IST Clock updater (Asia/Kolkata)
 */
function updateISTClock() {
  const clockEl = document.getElementById("currentClock");
  if (!clockEl) return;
  
  try {
    const now = new Date();
    const timeOptions = {
      timeZone: "Asia/Kolkata",
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    };
    const timeStr = new Intl.DateTimeFormat("en-GB", timeOptions).format(now);
    clockEl.textContent = `${timeStr} IST`;
  } catch (e) {
    clockEl.textContent = new Date().toLocaleTimeString();
  }
}

/**
 * Global Tooltip Management
 */
function showTooltip(evt, textHtml) {
  const tooltip = document.getElementById("chartTooltip");
  if (!tooltip) return;
  tooltip.innerHTML = textHtml;
  tooltip.classList.remove("hidden");
  
  const x = evt.pageX + 10;
  const y = evt.pageY - 35;
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
}

function hideTooltip() {
  const tooltip = document.getElementById("chartTooltip");
  if (tooltip) {
    tooltip.classList.add("hidden");
  }
}

/**
 * Load System & Router Status
 */
async function loadStatus() {
  try {
    const data = await getJSON("/status");
    
    // Header
    const routerIdentity = document.getElementById("routerIdentity");
    const statusDot = document.getElementById("statusDot");
    const connectionStatus = document.getElementById("connectionStatus");
    const lastUpdated = document.getElementById("lastUpdated");
    const footerMode = document.getElementById("footerModeStatus");

    if (routerIdentity) routerIdentity.textContent = data.router?.identity || "Jio Router";
    if (footerMode) footerMode.textContent = `Mode: ${(data.router?.mode || "MOCK").toUpperCase()}`;
    
    const isOnline = (data.status === "online" || data.router?.connected);
    if (statusDot) {
      statusDot.className = isOnline ? "pulse-dot" : "pulse-dot disconnected";
    }
    if (connectionStatus) {
      connectionStatus.textContent = isOnline ? "ONLINE" : "OFFLINE";
    }

    if (lastUpdated) {
      const now = new Date();
      lastUpdated.textContent = now.toLocaleTimeString();
    }

    // Network Status Card
    const netCardRouterStatus = document.getElementById("netCardRouterStatus");
    const netCardConnStatus = document.getElementById("netCardConnStatus");
    const netCardLastUpdated = document.getElementById("netCardLastUpdated");
    if (netCardRouterStatus) netCardRouterStatus.textContent = data.router?.identity || "Online";
    if (netCardConnStatus) netCardConnStatus.textContent = isOnline ? "Connected" : "Disconnected";
    if (netCardLastUpdated) netCardLastUpdated.textContent = new Date().toLocaleTimeString();

    // Network Tab
    const netTabRouterIdentity = document.getElementById("netTabRouterIdentity");
    const netTabRouterHost = document.getElementById("netTabRouterHost");
    const netTabRouterStatus = document.getElementById("netTabRouterStatus");
    const netTabOperatingMode = document.getElementById("netTabOperatingMode");
    const netTabKnownDevices = document.getElementById("netTabKnownDevices");

    if (netTabRouterIdentity) netTabRouterIdentity.textContent = data.router?.identity || "Jio Router";
    if (netTabRouterHost) netTabRouterHost.textContent = data.router?.host || "192.168.29.1";
    if (netTabRouterStatus) netTabRouterStatus.textContent = isOnline ? "Online" : "Offline";
    if (netTabOperatingMode) netTabOperatingMode.textContent = (data.router?.mode || "MOCK").toUpperCase();
    if (netTabKnownDevices) netTabKnownDevices.textContent = data.devices?.known_count ?? allDevicesCache.length;

    // Settings Tab
    const cfgRouterHost = document.getElementById("cfgRouterHost");
    const cfgRouterIdentity = document.getElementById("cfgRouterIdentity");
    const cfgRouterMode = document.getElementById("cfgRouterMode");
    const cfgCollectionInterval = document.getElementById("cfgCollectionInterval");
    const cfgRefreshInterval = document.getElementById("cfgRefreshInterval");

    if (cfgRouterHost) cfgRouterHost.textContent = data.router?.host || "192.168.29.1";
    if (cfgRouterIdentity) cfgRouterIdentity.textContent = data.router?.identity || "Jio Router";
    if (cfgRouterMode) cfgRouterMode.textContent = data.collector?.mode || data.router?.mode || "mock";
    if (cfgCollectionInterval) cfgCollectionInterval.textContent = `${data.collector?.collection_interval_seconds || 60} seconds`;
    if (cfgRefreshInterval) cfgRefreshInterval.textContent = `${data.system?.dashboard_refresh_interval_seconds || 15} seconds`;

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

    // Also populate Network Status Card
    const netCardDownload = document.getElementById("netCardDownload");
    const netCardUpload = document.getElementById("netCardUpload");
    const netCardTotal = document.getElementById("netCardTotal");

    if (netCardDownload) netCardDownload.textContent = formatBytes(data.download_bytes);
    if (netCardUpload) netCardUpload.textContent = formatBytes(data.upload_bytes);
    if (netCardTotal) netCardTotal.textContent = formatBytes(data.total_bytes);
  } catch (err) {
    const valTotalToday = document.getElementById("valTotalToday");
    if (valTotalToday) valTotalToday.textContent = "Unavailable";
  }
}

/**
 * Load and Render 24-Hour Timeline Chart
 * CRITICAL: Must ALWAYS contain all 24 hours (00:00 to 23:00)
 */
async function loadHourlyUsage() {
  const container = document.getElementById("hourlyChart");
  if (!container) return;

  try {
    const data = await getJSON("/usage/hourly");
    const rawHours = data.hours || [];
    
    // Ensure 24 hours guaranteed
    const fullHours = [];
    const hourMap = {};
    rawHours.forEach(h => {
      if (h.hour) hourMap[h.hour.substring(0, 2)] = h;
    });

    for (let i = 0; i < 24; i++) {
      const hStr = String(i).padStart(2, "0");
      const key = `${hStr}:00`;
      if (hourMap[hStr]) {
        fullHours.push(hourMap[hStr]);
      } else {
        fullHours.push({
          hour: key,
          download_bytes: 0,
          upload_bytes: 0,
          total_bytes: 0
        });
      }
    }

    renderHourlyChart(fullHours);
  } catch (err) {
    container.innerHTML = `<p class="placeholder-text" style="color: var(--color-danger);">HOURLY DATA UNAVAILABLE</p>`;
  }
}

/**
 * Render 24-Hour SVG Stacked Bar Chart
 */
function renderHourlyChart(hours) {
  const container = document.getElementById("hourlyChart");
  if (!container) return;

  // Find max value for scaling
  let maxBytes = 1024 * 1024; // minimum 1MB baseline
  hours.forEach(h => {
    const tot = (h.download_bytes || 0) + (h.upload_bytes || 0);
    if (tot > maxBytes) maxBytes = tot;
  });

  const width = 620;
  const height = 210;
  const paddingLeft = 55;
  const paddingBottom = 25;
  const paddingTop = 15;
  const paddingRight = 15;

  const chartW = width - paddingLeft - paddingRight;
  const chartH = height - paddingTop - paddingBottom;
  const slotW = chartW / 24;
  const barW = Math.max(3, slotW - 4);

  let barsSvg = "";
  let xLabels = "";

  hours.forEach((item, index) => {
    const x = paddingLeft + (index * slotW) + 2;
    const dlBytes = item.download_bytes || 0;
    const ulBytes = item.upload_bytes || 0;
    const totBytes = dlBytes + ulBytes;

    const dlHeight = (dlBytes / maxBytes) * chartH;
    const ulHeight = (ulBytes / maxBytes) * chartH;

    const yDl = paddingTop + chartH - dlHeight;
    const yUl = yDl - ulHeight;

    const tooltipHtml = `<strong>Hour: ${item.hour}</strong><br>Download: <span style="color:#F06021">${formatBytes(dlBytes)}</span><br>Upload: <span style="color:#6B9CAA">${formatBytes(ulBytes)}</span><br>Total: <strong>${formatBytes(totBytes)}</strong>`;

    barsSvg += `
      <g class="chart-hour-bar"
         onmousemove="showTooltip(event, '${tooltipHtml.replace(/'/g, "\\'")}')"
         onmouseleave="hideTooltip()">
        <!-- Background hit area for easy hover -->
        <rect x="${x - 1}" y="${paddingTop}" width="${barW + 2}" height="${chartH}" fill="transparent" />
        <!-- Download (Orange) -->
        <rect x="${x}" y="${yDl}" width="${barW}" height="${Math.max(0, dlHeight)}" fill="#F06021" rx="1" />
        <!-- Upload (Teal) stacked on top -->
        <rect x="${x}" y="${yUl}" width="${barW}" height="${Math.max(0, ulHeight)}" fill="#6B9CAA" rx="1" />
      </g>
    `;

    // Render labels every 3 hours (00, 03, 06, 09, 12, 15, 18, 21, 23)
    if (index % 3 === 0 || index === 23) {
      xLabels += `<text x="${x + (barW / 2)}" y="${height - 6}" font-size="9" fill="#8b949e" text-anchor="middle" font-family="'JetBrains Mono', monospace">${item.hour.substring(0, 2)}:00</text>`;
    }
  });

  // Horizontal grid lines
  const gridLines = `
    <line x1="${paddingLeft}" y1="${paddingTop}" x2="${width - paddingRight}" y2="${paddingTop}" stroke="#242933" stroke-dasharray="3,3" />
    <line x1="${paddingLeft}" y1="${paddingTop + chartH / 2}" x2="${width - paddingRight}" y2="${paddingTop + chartH / 2}" stroke="#242933" stroke-dasharray="3,3" />
    <line x1="${paddingLeft}" y1="${paddingTop + chartH}" x2="${width - paddingRight}" y2="${paddingTop + chartH}" stroke="#4D4D4D" />
    <text x="${paddingLeft - 8}" y="${paddingTop + 4}" font-size="8" fill="#8b949e" text-anchor="end" font-family="'JetBrains Mono', monospace">${formatBytes(maxBytes, 0)}</text>
    <text x="${paddingLeft - 8}" y="${paddingTop + chartH / 2 + 3}" font-size="8" fill="#8b949e" text-anchor="end" font-family="'JetBrains Mono', monospace">${formatBytes(maxBytes / 2, 0)}</text>
    <text x="${paddingLeft - 8}" y="${paddingTop + chartH}" font-size="8" fill="#8b949e" text-anchor="end" font-family="'JetBrains Mono', monospace">0 B</text>
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
    allDevicesCache = devices;

    // Update active vs total count
    const activeCount = devices.filter(d => d.is_active).length;
    const totalCount = devices.length;
    
    const activeDevicesEl = document.getElementById("valActiveDevices");
    const devicesSubtextEl = document.getElementById("valDevicesSubtext");
    if (activeDevicesEl) activeDevicesEl.textContent = activeCount;
    if (devicesSubtextEl) devicesSubtextEl.textContent = `${activeCount} active / ${totalCount} registered`;

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

  // Render top devices in Overview
  if (overviewBody) {
    const topDevices = devices.slice(0, 8);
    overviewBody.innerHTML = topDevices.map(dev => `
      <tr class="clickable" onclick="openDevice('${dev.mac_address}')" title="Click to view details for ${dev.hostname || dev.mac_address}">
        <td><strong>${dev.hostname || "Unknown Device"}</strong><br><small style="color:var(--color-text-muted); font-size:0.75rem;">${dev.mac_address}</small></td>
        <td>${dev.ip_address || "--"}</td>
        <td style="color:var(--color-orange);">${formatBytes(dev.download_bytes)}</td>
        <td style="color:var(--color-teal);">${formatBytes(dev.upload_bytes)}</td>
        <td><strong>${formatBytes(dev.total_bytes)}</strong></td>
        <td>${dev.last_seen ? new Date(dev.last_seen).toLocaleTimeString() : "--"}</td>
        <td><span class="badge-pill ${dev.is_active ? 'active' : 'inactive'}">${dev.is_active ? 'ONLINE' : 'IDLE'}</span></td>
      </tr>
    `).join("");
  }

  // Render all in Devices tab (accounting for search filter)
  renderFullDevicesTable(devices);
}

/**
 * Render Full Devices Tab Table with Filtering
 */
function renderFullDevicesTable(devices) {
  const fullBody = document.getElementById("fullDevicesBody");
  if (!fullBody) return;

  const searchInput = document.getElementById("deviceSearchInput");
  const query = (searchInput?.value || "").trim().toLowerCase();

  const filtered = query
    ? devices.filter(d =>
        (d.hostname && d.hostname.toLowerCase().includes(query)) ||
        (d.mac_address && d.mac_address.toLowerCase().includes(query)) ||
        (d.ip_address && d.ip_address.toLowerCase().includes(query)) ||
        (d.ssid && d.ssid.toLowerCase().includes(query))
      )
    : devices;

  if (filtered.length === 0) {
    fullBody.innerHTML = `<tr><td colspan="8" class="table-empty">No matching devices found.</td></tr>`;
    return;
  }

  fullBody.innerHTML = filtered.map(dev => `
    <tr class="clickable" onclick="openDevice('${dev.mac_address}')" title="Click to view device telemetry">
      <td><strong>${dev.hostname || "Unknown Device"}</strong></td>
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

/**
 * Render Usage Distribution Donut Chart with Deterministic Palette
 */
function renderDistribution(devices) {
  const container = document.getElementById("distribution");
  if (!container) return;

  const activeWithUsage = devices.filter(d => (d.total_bytes || 0) > 0);
  if (!activeWithUsage.length) {
    container.innerHTML = `<p class="placeholder-text">No traffic usage recorded to distribute yet today.</p>`;
    return;
  }

  const grandTotal = activeWithUsage.reduce((sum, d) => sum + (d.total_bytes || 0), 0);
  let cumulativePercent = 0;
  const segments = [];

  activeWithUsage.forEach(dev => {
    const bytes = dev.total_bytes || 0;
    const percent = grandTotal > 0 ? (bytes / grandTotal) * 100 : 0;
    const color = getDeviceColor(dev.mac_address);
    segments.push({
      mac: dev.mac_address,
      name: dev.hostname || dev.mac_address.substring(dev.mac_address.length - 8),
      bytes: bytes,
      percent: percent,
      color: color,
      offset: cumulativePercent
    });
    cumulativePercent += percent;
  });

  // SVG Donut (circumference = 2 * PI * 40 = 251.327)
  const C = 251.327;
  let circlesSvg = "";
  let legendItems = "";

  segments.forEach(seg => {
    const strokeDash = (seg.percent / 100) * C;
    const strokeOffset = -(seg.offset / 100) * C;
    const tooltipHtml = `<strong>${seg.name}</strong><br>Traffic: <strong>${formatBytes(seg.bytes)}</strong><br>Share: <strong>${seg.percent.toFixed(1)}%</strong>`;

    circlesSvg += `
      <circle class="donut-segment" r="40" cx="50" cy="50" fill="transparent"
        stroke="${seg.color}"
        stroke-width="14"
        stroke-dasharray="${strokeDash} ${C - strokeDash}"
        stroke-dashoffset="${strokeOffset}"
        onmousemove="showTooltip(event, '${tooltipHtml.replace(/'/g, "\\'")}')"
        onmouseleave="hideTooltip()"
      />
    `;

    legendItems += `
      <div class="donut-legend-item">
        <span class="donut-color-swatch" style="background-color: ${seg.color}"></span>
        <span style="color: #ffffff; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${seg.name}">${seg.name}</span>
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
 * Load and Render Network Statistics
 */
async function loadNetworkStats() {
  try {
    const stats = await getJSON("/network/stats");
    
    // Overview mini stats
    const netDl = document.getElementById("netStatDownload");
    const netUl = document.getElementById("netStatUpload");
    const rxB = document.getElementById("netRxBytes");
    const txB = document.getElementById("netTxBytes");
    const rxP = document.getElementById("netRxPkts");
    const txP = document.getElementById("netTxPkts");
    const rxE = document.getElementById("netRxErrors");
    const txE = document.getElementById("netTxErrors");
    const rxD = document.getElementById("netRxDropped");
    const txD = document.getElementById("netTxDropped");

    if (netDl) netDl.textContent = formatBytes(stats.download_bytes);
    if (netUl) netUl.textContent = formatBytes(stats.upload_bytes);
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
    const netFullRxB = document.getElementById("netFullRxBytes");
    const netFullTxB = document.getElementById("netFullTxBytes");
    const netFullRxP = document.getElementById("netFullRxPkts");
    const netFullTxP = document.getElementById("netFullTxPkts");
    const netFullRxE = document.getElementById("netFullRxErrors");
    const netFullTxE = document.getElementById("netFullTxErrors");
    const netFullRxD = document.getElementById("netFullRxDropped");
    const netFullTxD = document.getElementById("netFullTxDropped");

    if (netFullDl) netFullDl.textContent = formatBytes(stats.download_bytes);
    if (netFullUl) netFullUl.textContent = formatBytes(stats.upload_bytes);
    if (netFullRxB) netFullRxB.textContent = formatBytes(stats.bytes_rx);
    if (netFullTxB) netFullTxB.textContent = formatBytes(stats.bytes_tx);
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
 * Load Historical Usage (Today, Yesterday, 7 Days, This Month, Daily Table)
 */
async function loadUsageHistory() {
  try {
    const [today, yest, week, month, daily] = await Promise.allSettled([
      getJSON("/usage/today"),
      getJSON("/usage/yesterday"),
      getJSON("/usage/7days"),
      getJSON("/usage/month"),
      getJSON("/usage/daily")
    ]);

    if (today.status === "fulfilled" && today.value) {
      const el = document.getElementById("histTodayTotal");
      const sub = document.getElementById("histTodaySub");
      if (el) el.textContent = formatBytes(today.value.total_bytes);
      if (sub) sub.textContent = `↓ ${formatBytes(today.value.download_bytes)}  ↑ ${formatBytes(today.value.upload_bytes)}`;
    }

    if (yest.status === "fulfilled" && yest.value) {
      const el = document.getElementById("histYesterdayTotal");
      const sub = document.getElementById("histYesterdaySub");
      if (el) el.textContent = formatBytes(yest.value.total_bytes);
      if (sub) sub.textContent = `↓ ${formatBytes(yest.value.download_bytes)}  ↑ ${formatBytes(yest.value.upload_bytes)}`;
    }

    if (week.status === "fulfilled" && week.value) {
      const el = document.getElementById("hist7DaysTotal");
      const sub = document.getElementById("hist7DaysSub");
      if (el) el.textContent = formatBytes(week.value.total_bytes);
      if (sub) sub.textContent = `↓ ${formatBytes(week.value.download_bytes)}  ↑ ${formatBytes(week.value.upload_bytes)}`;
    }

    if (month.status === "fulfilled" && month.value) {
      const el = document.getElementById("histMonthTotal");
      const sub = document.getElementById("histMonthSub");
      if (el) el.textContent = formatBytes(month.value.total_bytes);
      if (sub) sub.textContent = `↓ ${formatBytes(month.value.download_bytes)}  ↑ ${formatBytes(month.value.upload_bytes)}`;
    }

    // Daily Table
    const dailyBody = document.getElementById("dailyUsageBody");
    if (dailyBody) {
      if (daily.status === "fulfilled" && daily.value && daily.value.days) {
        const days = daily.value.days;
        if (days.length === 0) {
          dailyBody.innerHTML = `<tr><td colspan="4" class="table-empty">No daily history recorded yet.</td></tr>`;
        } else {
          // Display in descending order for natural timeline reading
          const sortedDays = [...days].reverse();
          dailyBody.innerHTML = sortedDays.map(d => {
            const dateStr = d.date || d.day || "--";
            return `
              <tr>
                <td><strong>${dateStr}</strong></td>
                <td style="color:var(--color-orange);">${formatBytes(d.download_bytes)}</td>
                <td style="color:var(--color-teal);">${formatBytes(d.upload_bytes)}</td>
                <td><strong>${formatBytes(d.total_bytes)}</strong></td>
              </tr>
            `;
          }).join("");
        }
      } else {
        dailyBody.innerHTML = `<tr><td colspan="4" class="table-empty" style="color:var(--color-danger);">Failed to load daily usage table.</td></tr>`;
      }
    }
  } catch (err) {
    console.error("Failed to load usage history:", err);
  }
}

/**
 * Open Device Details view
 * Uses: /api/devices/<mac>, /api/devices/<mac>/daily, /api/devices/<mac>/stats
 */
async function openDevice(mac) {
  const panel = document.getElementById("deviceDetails");
  if (!panel) return;

  activeDeviceMac = mac;

  // Switch tab to devices if not already there
  const tabBtn = document.getElementById("tab-devices");
  if (tabBtn && !tabBtn.classList.contains("active")) {
    tabBtn.click();
  }

  panel.classList.remove("hidden");
  panel.scrollIntoView({ behavior: "smooth", block: "start" });

  const nameEl = document.getElementById("detailDeviceName");
  const macEl = document.getElementById("detailDeviceMac");
  const ipEl = document.getElementById("detailDeviceIp");
  const radioEl = document.getElementById("detailDeviceRadio");
  const ssidEl = document.getElementById("detailDeviceSsid");
  const apEl = document.getElementById("detailDeviceAp");
  const lastSeenEl = document.getElementById("detailDeviceLastSeen");
  const statusEl = document.getElementById("detailDeviceStatus");

  if (nameEl) nameEl.textContent = "Loading Device Details...";
  if (macEl) macEl.textContent = mac;

  try {
    const [devRes, dailyRes, statsRes] = await Promise.allSettled([
      getJSON(`/devices/${mac}`),
      getJSON(`/devices/${mac}/daily`),
      getJSON(`/devices/${mac}/stats`)
    ]);

    // 1. Device Metadata & 4 Period Usage Cards
    if (devRes.status === "fulfilled" && devRes.value) {
      const dev = devRes.value;
      if (nameEl) nameEl.textContent = dev.hostname || "Device Details";
      if (macEl) macEl.textContent = dev.mac_address || mac;
      if (ipEl) ipEl.textContent = `IP: ${dev.ip_address || "--"}`;
      if (radioEl) radioEl.textContent = `Radio: ${dev.radio || "--"}`;
      if (ssidEl) ssidEl.textContent = `SSID: ${dev.ssid || "--"}`;
      if (apEl) apEl.textContent = `AP: ${dev.ap || "--"}`;
      if (lastSeenEl) lastSeenEl.textContent = `Last Seen: ${dev.last_seen ? new Date(dev.last_seen).toLocaleString() : "--"}`;
      if (statusEl) {
        statusEl.className = dev.is_active ? "badge-pill active" : "badge-pill inactive";
        statusEl.textContent = dev.is_active ? "ONLINE" : "IDLE";
      }

      // Populate 4 Usage Cards from /api/devices/<mac>
      const u = dev.usage || {};
      const t = u.today || { total_bytes: 0, download_bytes: 0, upload_bytes: 0 };
      const y = u.yesterday || { total_bytes: 0, download_bytes: 0, upload_bytes: 0 };
      const w = u.last_7_days || { total_bytes: 0, download_bytes: 0, upload_bytes: 0 };
      const m = u.this_month || { total_bytes: 0, download_bytes: 0, upload_bytes: 0 };

      const devToday = document.getElementById("devUsageToday");
      const devTodaySub = document.getElementById("devUsageTodayBreakdown");
      if (devToday) devToday.textContent = formatBytes(t.total_bytes);
      if (devTodaySub) devTodaySub.textContent = `↓ ${formatBytes(t.download_bytes)}  ↑ ${formatBytes(t.upload_bytes)}`;

      const devYest = document.getElementById("devUsageYesterday");
      const devYestSub = document.getElementById("devUsageYesterdayBreakdown");
      if (devYest) devYest.textContent = formatBytes(y.total_bytes);
      if (devYestSub) devYestSub.textContent = `↓ ${formatBytes(y.download_bytes)}  ↑ ${formatBytes(y.upload_bytes)}`;

      const dev7Days = document.getElementById("devUsage7Days");
      const dev7DaysSub = document.getElementById("devUsage7DaysBreakdown");
      if (dev7Days) dev7Days.textContent = formatBytes(w.total_bytes);
      if (dev7DaysSub) dev7DaysSub.textContent = `↓ ${formatBytes(w.download_bytes)}  ↑ ${formatBytes(w.upload_bytes)}`;

      const devMonth = document.getElementById("devUsageMonth");
      const devMonthSub = document.getElementById("devUsageMonthBreakdown");
      if (devMonth) devMonth.textContent = formatBytes(m.total_bytes);
      if (devMonthSub) devMonthSub.textContent = `↓ ${formatBytes(m.download_bytes)}  ↑ ${formatBytes(m.upload_bytes)}`;
    }

    // 2. Device 7-Day History Chart/List
    const chartBox = document.getElementById("deviceDailyChart");
    if (chartBox) {
      if (dailyRes.status === "fulfilled" && dailyRes.value && dailyRes.value.days) {
        const days = dailyRes.value.days;
        if (days.length === 0) {
          chartBox.innerHTML = `<p class="placeholder-text">No daily records for this device.</p>`;
        } else {
          chartBox.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 0.5rem;">
              ${days.map(d => {
                const dateStr = d.date || d.day || "--";
                return `
                  <div style="display: flex; justify-content: space-between; align-items: center; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.05); padding: 0.4rem 0;">
                    <span style="font-weight:600;">${dateStr}</span>
                    <span>
                      <span style="color:var(--color-orange);">↓ ${formatBytes(d.download_bytes)}</span> &nbsp;|&nbsp; 
                      <span style="color:var(--color-teal);">↑ ${formatBytes(d.upload_bytes)}</span>
                    </span>
                    <strong>${formatBytes(d.total_bytes)}</strong>
                  </div>
                `;
              }).join("")}
            </div>
          `;
        }
      } else {
        chartBox.innerHTML = `<p class="placeholder-text" style="color:var(--color-danger);">Failed to load device daily history.</p>`;
      }
    }

    // 3. Device Network Counters
    if (statsRes.status === "fulfilled" && statsRes.value) {
      const stats = statsRes.value;
      const devDl = document.getElementById("devStatDownload");
      const devUl = document.getElementById("devStatUpload");
      const rxB = document.getElementById("devStatRxBytes");
      const txB = document.getElementById("devStatTxBytes");
      const rxP = document.getElementById("devStatRxPkts");
      const txP = document.getElementById("devStatTxPkts");
      const rxE = document.getElementById("devStatRxErrors");
      const txE = document.getElementById("devStatTxErrors");
      const rxD = document.getElementById("devStatRxDropped");
      const txD = document.getElementById("devStatTxDropped");

      if (devDl) devDl.textContent = formatBytes(stats.download_bytes);
      if (devUl) devUl.textContent = formatBytes(stats.upload_bytes);
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
    console.error("Failed to load device details for", mac, err);
  }
}

/**
 * Initialize Navigation & Event Handlers
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
      } else if (tab.dataset.tab === "devices") {
        renderFullDevicesTable(allDevicesCache);
      }
    });
  });

  // Back button in Device Details
  const backBtn = document.getElementById("btnBackToDevices");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      const panel = document.getElementById("deviceDetails");
      if (panel) panel.classList.add("hidden");
      activeDeviceMac = null;
    });
  }

  // Device Search Filter
  const searchInput = document.getElementById("deviceSearchInput");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      renderFullDevicesTable(allDevicesCache);
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

  // If a device details panel is currently open, refresh it as well
  if (activeDeviceMac) {
    openDevice(activeDeviceMac);
  }
}

/**
 * DOM Ready Bootstrap
 */
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  
  // Start clock updater
  updateISTClock();
  setInterval(updateISTClock, 1000);

  // Initial load
  refreshAll();

  // Periodic monitoring refresh cycle (15s)
  setInterval(refreshAll, 15000);
});
