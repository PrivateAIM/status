const maxBlocks = 30;
const statusLookbackMinutes = 45; // Configurable window for overall status badges

// Resolution modes: each defines the duration of one block in milliseconds,
// a human-readable label for tooltips, and a formatter for tooltip dates.
const resolutions = {
  "1d":    { ms: 24 * 3600 * 1000, label: "1 day" },
  "6h":    { ms:  6 * 3600 * 1000, label: "6 hours" },
  "30min": { ms:      30 * 60000,  label: "30 min" },
};

let currentResolution = "30min";

// Cached raw log text per key so we can re-render without re-fetching.
let rawLogCache = {};
// Cached config lines so we can rebuild the report section.
let configCache = [];

function getSlotMs() {
  return resolutions[currentResolution].ms;
}

// ─── Tooltip date formatting ────────────────────────────────────────────
function formatSlotDate(date) {
  if (currentResolution === "1d") {
    return date.toDateString();
  }
  return date.toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// ─── Report generation ──────────────────────────────────────────────────
async function genReportLog(container, key, url) {
  let statusLines = rawLogCache[key];
  if (statusLines === undefined) {
    const response = await fetch("logs/" + key + "_report.log");
    statusLines = response.ok ? await response.text() : "";
    rawLogCache[key] = statusLines;
  }

  const normalized = normalizeData(statusLines);
  const statusStream = constructStatusStream(key, url, normalized);
  container.appendChild(statusStream);

  return normalized;
}

function constructStatusStream(key, url, uptimeData) {
  let streamContainer = templatize("statusStreamContainerTemplate");
  for (var ii = maxBlocks - 1; ii >= 0; ii--) {
    let line = constructStatusBlock(key, ii, uptimeData[ii]);
    streamContainer.appendChild(line);
  }

  const lastUptime = uptimeData.overallUptime;
  const color = getColor(lastUptime);

  const durationText = uptimeData.latestDuration !== null && uptimeData.latestDuration !== undefined
    ? `Latest run: ${uptimeData.latestDuration.toFixed(1)}s`
    : "Latest run: --";

  const container = templatize("statusContainerTemplate", {
    title: key,
    url: url,
    color: color,
    status: getStatusText(color),
    upTime: uptimeData.upTime,
    upDays: uptimeData.coveredLabel,
    latestDuration: durationText,
  });

  container.appendChild(streamContainer);
  return container;
}

function constructStatusBlock(key, relSlot, slotData) {
  const slotMs = getSlotMs();
  const now = Date.now();
  const slotEnd = now - relSlot * slotMs;
  const date = new Date(slotEnd);

  return constructStatusSquare(key, date, slotData);
}

function getColor(uptimeVal) {
  return uptimeVal == null
    ? "nodata"
    : uptimeVal == 1
    ? "success"
    : uptimeVal < 0.3
    ? "failure"
    : "partial";
}

function constructStatusSquare(key, date, slotData) {
  const uptimeVal = slotData ? slotData.uptime : null;
  const durationVal = slotData ? slotData.duration : null;
  const color = getColor(uptimeVal);

  let square = templatize("statusSquareTemplate", {
    color: color,
    tooltip: getTooltip(key, date, color, durationVal),
  });

  const show = () => {
    showTooltip(square, key, date, color, durationVal);
  };
  square.addEventListener("mouseover", show);
  square.addEventListener("mousedown", show);
  square.addEventListener("mouseout", hideTooltip);
  return square;
}

let cloneId = 0;
function templatize(templateId, parameters) {
  let clone = document.getElementById(templateId).cloneNode(true);
  clone.id = "template_clone_" + cloneId++;
  if (!parameters) {
    return clone;
  }

  applyTemplateSubstitutions(clone, parameters);
  return clone;
}

function applyTemplateSubstitutions(node, parameters) {
  const attributes = node.getAttributeNames();
  for (var ii = 0; ii < attributes.length; ii++) {
    const attr = attributes[ii];
    const attrVal = node.getAttribute(attr);
    node.setAttribute(attr, templatizeString(attrVal, parameters));
  }

  if (node.childElementCount == 0) {
    node.innerText = templatizeString(node.innerText, parameters);
  } else {
    const children = Array.from(node.children);
    children.forEach((n) => {
      applyTemplateSubstitutions(n, parameters);
    });
  }
}

function templatizeString(text, parameters) {
  if (parameters) {
    for (const [key, val] of Object.entries(parameters)) {
      text = text.replaceAll("$" + key, val);
    }
  }
  return text;
}

function getStatusText(color) {
  return color == "nodata"
    ? "No Data Available"
    : color == "success"
    ? "Fully Operational"
    : color == "failure"
    ? "Major Outage"
    : color == "partial"
    ? "Partial Outage"
    : "Unknown";
}

function getStatusDescriptiveText(color) {
  return color == "nodata"
    ? "No Data Available: Health check was not performed."
    : color == "success"
    ? "No downtime recorded in this period."
    : color == "failure"
    ? "Major outages recorded in this period."
    : color == "partial"
    ? "Partial outages recorded in this period."
    : "Unknown";
}

function getTooltip(key, date, color, duration) {
  let statusText = getStatusText(color);
  const durText = duration !== null && duration !== undefined ? ` (${duration.toFixed(1)}s)` : "";
  return `${key} | ${formatSlotDate(date)} : ${statusText}${durText}`;
}

function create(tag, className) {
  let element = document.createElement(tag);
  element.className = className;
  return element;
}

// ─── Data normalization ─────────────────────────────────────────────────
// Buckets log rows into relative time slots of configurable width.
function normalizeData(statusLines) {
  const rows = statusLines.split("\n");
  const parsedRows = parseRows(rows);

  const slotMs = getSlotMs();
  const now = Date.now();

  let relativeSlotMap = {};
  let sum = 0, count = 0, slotsWithData = 0;

  for (const entry of parsedRows) {
    const age = now - entry.timestamp;
    if (age < 0) continue;
    const relSlot = Math.floor(age / slotMs);
    if (relSlot >= maxBlocks) continue;

    if (!relativeSlotMap[relSlot]) {
      relativeSlotMap[relSlot] = { results: [], durations: [] };
    }

    relativeSlotMap[relSlot].results.push(entry.result);
    if (entry.duration !== null) {
      relativeSlotMap[relSlot].durations.push(entry.duration);
    }
  }

  // Aggregate each slot
  for (const [slot, data] of Object.entries(relativeSlotMap)) {
    slotsWithData++;
    sum += data.results.reduce((a, b) => a + b, 0);
    count += data.results.length;

    relativeSlotMap[slot] = {
      uptime: getAverage(data.results),
      duration: getAverage(data.durations),
    };
  }

  const validRows = rows.filter(r => r.trim().length > 0);
  const lookbackMs = statusLookbackMinutes * 60000;
  let recentResults = [];
  
  for (const row of validRows) {
    const parts = row.split(",");
    const dateTimeStr = parts[0];
    const timestamp = Date.parse(dateTimeStr.replace(/-/g, "/") + " GMT");
    if (isNaN(timestamp)) continue;
    
    if (now - timestamp <= lookbackMs && now - timestamp >= 0) {
      const resultStr = parts[1] ? parts[1].trim() : "";
      if (resultStr === "success") recentResults.push(1);
      else if (resultStr === "failed" || resultStr === "failure") recentResults.push(0);
    }
  }
  relativeSlotMap.overallUptime = recentResults.length > 0 ? getAverage(recentResults) : null;

  relativeSlotMap.upTime = count ? ((sum / count) * 100).toFixed(2) + "%" : "--%";
  relativeSlotMap.coveredLabel = formatCoveredLabel(slotsWithData);
  relativeSlotMap.latestDuration = parsedRows.length > 0 ? parsedRows[parsedRows.length - 1].duration : null;
  relativeSlotMap.latestTimestamp = parsedRows.length > 0 ? new Date(parsedRows[parsedRows.length - 1].timestamp) : null;
  return relativeSlotMap;
}

// Formats the "covered period" label based on current resolution.
function formatCoveredLabel(slotsWithData) {
  if (currentResolution === "1d") {
    return slotsWithData + "d";
  }
  const totalHours = slotsWithData * (getSlotMs() / 3600000);
  if (totalHours >= 24) {
    return (totalHours / 24).toFixed(1) + "d";
  }
  return totalHours.toFixed(1) + "h";
}

function parseRows(rows) {
  let entries = [];
  for (var ii = 0; ii < rows.length; ii++) {
    const row = rows[ii];
    if (!row) continue;

    const parts = row.split(",");
    const dateTimeStr = parts[0];
    const resultStr = parts[1] ? parts[1].trim() : "";
    const duration = parts[2] ? parseFloat(parts[2].trim()) : null;

    const timestamp = Date.parse(dateTimeStr.replace(/-/g, "/") + " GMT");
    if (isNaN(timestamp)) continue;

    // "unknown" means the step never ran (an earlier step failed);
    // exclude it from uptime statistics instead of counting it as failure.
    if (resultStr == "unknown") continue;

    let result = resultStr == "success" ? 1 : 0;
    entries.push({
      timestamp: timestamp,
      result: result,
      duration: duration !== null && !isNaN(duration) ? duration : null,
    });
  }
  return entries;
}

function getAverage(arr) {
  if (!arr || arr.length === 0) {
    return null;
  }
  const valid = arr.filter((v) => v !== null && !isNaN(v));
  if (valid.length === 0) {
    return null;
  }
  return valid.reduce((a, b) => a + b, 0) / valid.length;
}

// ─── Tooltip ────────────────────────────────────────────────────────────
let tooltipTimeout = null;
function showTooltip(element, key, date, color, duration) {
  clearTimeout(tooltipTimeout);
  const toolTipDiv = document.getElementById("tooltip");

  document.getElementById("tooltipDateTime").innerText = formatSlotDate(date);

  let descText = getStatusDescriptiveText(color);
  if (duration !== null && duration !== undefined && color === "success") {
    descText += ` Average run duration: ${duration.toFixed(1)}s.`;
  }
  document.getElementById("tooltipDescription").innerText = descText;

  const statusDiv = document.getElementById("tooltipStatus");
  statusDiv.innerText = getStatusText(color);
  statusDiv.className = color;

  const rect = element.getBoundingClientRect();
  toolTipDiv.style.top = rect.bottom + window.scrollY + 10 + "px";
  toolTipDiv.style.left =
    rect.left + window.scrollX + rect.width / 2 - toolTipDiv.offsetWidth / 2 + "px";
  toolTipDiv.style.opacity = "1";
}

function hideTooltip() {
  tooltipTimeout = setTimeout(() => {
    const toolTipDiv = document.getElementById("tooltip");
    toolTipDiv.style.opacity = "0";
  }, 1000);
}

// ─── Messages ───────────────────────────────────────────────────────────
async function genMessages() {
  const container = document.getElementById("messages");
  const response = await fetch("messages.json");
  if (!response.ok) {
    return;
  }

  const messages = await response.json();
  messages.sort((a, b) => new Date(b.date) - new Date(a.date));

  for (const msg of messages) {
    const card = create("div", "messageCard " + msg.type);

    const header = create("div", "messageHeader");
    const title = create("span", "messageTitle");
    title.innerText = msg.title;
    const date = create("span", "messageDate");
    date.innerText = msg.date;
    header.appendChild(title);
    header.appendChild(date);

    const text = create("div", "messageText");
    text.innerText = msg.text;

    card.appendChild(header);
    card.appendChild(text);
    container.appendChild(card);
  }
}

// ─── Main report loop ───────────────────────────────────────────────────
async function genAllReports() {
  if (configCache.length === 0) {
    const response = await fetch("urls.cfg");
    const configText = await response.text();
    configCache = configText.split("\n").filter((l) => l.includes("="));
  }

  const reportsEl = document.getElementById("reports");
  reportsEl.innerHTML = "";

  let globalLatestTimestamp = null;
  let allUptimes = [];

  for (let ii = 0; ii < configCache.length; ii++) {
    const [key, url] = configCache[ii].split("=");
    if (!key || !url) continue;

    const normalized = await genReportLog(reportsEl, key, url);
    const ts = normalized.latestTimestamp;
    if (ts && (!globalLatestTimestamp || ts > globalLatestTimestamp)) {
      globalLatestTimestamp = ts;
    }
    allUptimes.push(normalized.overallUptime);
  }

  // Update overall badge
  const badgeEl = document.getElementById("overall-status-badge");
  if (badgeEl) {
    const colors = allUptimes.map(u => getColor(u));
    let overallColor = "nodata";
    if (colors.includes("failure")) overallColor = "failure";
    else if (colors.includes("partial")) overallColor = "partial";
    else if (colors.includes("success")) overallColor = "success";

    badgeEl.className = "overall-badge status-indicator-badge " + overallColor;
    badgeEl.innerText = getStatusText(overallColor);
  }

  if (globalLatestTimestamp) {
    const lastCheckEl = document.getElementById("last-check-info");
    if (lastCheckEl) {
      const nowTime = new Date().toLocaleTimeString();
      lastCheckEl.innerText = "Last check performed: " + globalLatestTimestamp.toLocaleString() + " (Page refreshed: " + nowTime + ")";
    }
  }
}

// ─── Resolution toggle ─────────────────────────────────────────────────
function initResolutionToggle() {
  const buttons = document.querySelectorAll(".res-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const newRes = btn.dataset.resolution;
      if (newRes === currentResolution) return;

      currentResolution = newRes;
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      // Update the window description text
      updateWindowLabel();

      // Re-render all reports with new resolution
      genAllReports();
    });
  });
  updateWindowLabel();
}

function updateWindowLabel() {
  const el = document.getElementById("resolution-window-label");
  if (!el) return;

  const totalMs = maxBlocks * getSlotMs();
  const totalHours = totalMs / 3600000;
  if (totalHours >= 24) {
    el.innerText = "Window: " + (totalHours / 24).toFixed(totalHours % 24 === 0 ? 0 : 1) + " days";
  } else {
    el.innerText = "Window: " + totalHours + " hours";
  }
}

// ─── Auto-Refresh ──────────────────────────────────────────────────────
let autoRefreshInterval = null;

function forceRefresh() {
  rawLogCache = {};
  genAllReports();
}

function initAutoRefresh() {
  const checkbox = document.getElementById("auto-refresh-checkbox");
  if (!checkbox) return;
  
  const applyAutoRefresh = () => {
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval);
      autoRefreshInterval = null;
    }
    if (checkbox.checked) {
      autoRefreshInterval = setInterval(() => {
        forceRefresh();
      }, 60000); // 1 minute
    }
  };

  checkbox.addEventListener("change", (e) => {
    if (e.target.checked) {
      forceRefresh();
    }
    applyAutoRefresh();
  });
  
  applyAutoRefresh();
}
