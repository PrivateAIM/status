import { CONFIG, getStatusText } from "./constants.js";
import { state } from "./state.js";
import { normalizeData, getSlotMs } from "./data.js";
import { showTooltipForSquare, hideTooltip } from "./tooltip.js";

// ─── DOM Helpers ────────────────────────────────────────────────────────
export function create(tag, className) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  return element;
}

export function templatize(templateId, parameters) {
  const template = document.getElementById(templateId);
  if (!template) return null;
  
  const clone = template.cloneNode(true);
  clone.id = "template_clone_" + state.cloneId++;
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

  if (node.childElementCount === 0) {
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

// ─── Color mappings ─────────────────────────────────────────────────────
export function getColor(uptimeVal) {
  return uptimeVal == null
    ? "nodata"
    : uptimeVal === 1
    ? "success"
    : uptimeVal < CONFIG.uptime.partialThreshold
    ? "failure"
    : "partial";
}

export function getLatencyColor(durationVal) {
  if (durationVal == null) return "nodata";
  if (durationVal < CONFIG.latency.successThreshold) return "success";
  if (durationVal < CONFIG.latency.partialThreshold) return "partial";
  return "failure";
}

// ─── Rendering and Card Updates ──────────────────────────────────────────
export function formatDurationText(latestDuration) {
  return latestDuration !== null && latestDuration !== undefined
    ? `Latest run: ${latestDuration.toFixed(1)}s`
    : "Latest run: --";
}

export function applySquareData(square, slotData) {
  const key = square.dataset.key;
  const uptimeVal = slotData ? slotData.uptime : null;
  const durationVal = slotData ? slotData.duration : null;
  const color = key === "latency" ? getLatencyColor(durationVal) : getColor(uptimeVal);

  square.className = "statusSquare " + color;
  square.dataset.status = color;
  square.dataset.duration = durationVal !== null && durationVal !== undefined ? durationVal : "";
}

export function constructStatusSquare(key, relSlot, slotData) {
  const square = templatize("statusSquareTemplate");
  if (!square) return null;
  
  square.dataset.slot = relSlot;
  square.dataset.key = key;
  applySquareData(square, slotData);

  square.addEventListener("mouseover", () => showTooltipForSquare(square));
  square.addEventListener("mousedown", () => showTooltipForSquare(square));
  square.addEventListener("mouseout", hideTooltip);
  return square;
}

export function constructStatusStream(key, url, desc, uptimeData) {
  const streamContainer = templatize("statusStreamContainerTemplate");
  for (let ii = CONFIG.maxBlocks - 1; ii >= 0; ii--) {
    const square = constructStatusSquare(key, ii, uptimeData[ii]);
    if (square) streamContainer.appendChild(square);
  }

  const lastUptime = uptimeData.overallUptime;
  const color = key === "latency" ? getLatencyColor(uptimeData.overallDuration) : getColor(lastUptime);

  const displayTitle = key === "latency" ? "E2E Latency" : key;
  const uptimeDetail = key === "latency"
    ? (uptimeData.avgDuration !== null ? `Average: ${uptimeData.avgDuration.toFixed(1)}s` : "Average: --") + ` (${uptimeData.coveredLabel})`
    : `${uptimeData.upTime} uptime (${uptimeData.coveredLabel})`;

  const container = templatize("statusContainerTemplate", {
    title: displayTitle,
    url: url,
    desc: desc,
    color: color,
    status: getStatusText(color),
    latestDuration: formatDurationText(uptimeData.latestDuration),
    uptimeDetail: uptimeDetail,
  });

  container.dataset.reportKey = key;
  container.appendChild(streamContainer);
  return container;
}

export function updateStatusContainer(reportEl, uptimeData, desc) {
  const key = reportEl.dataset.reportKey;
  const color = key === "latency" ? getLatencyColor(uptimeData.overallDuration) : getColor(uptimeData.overallUptime);

  const badge = reportEl.querySelector(".status-indicator-badge");
  if (badge) {
    badge.className = "status-indicator-badge " + color;
    badge.innerText = getStatusText(color);
  }

  const urlEl = reportEl.querySelector(".sectionUrl a");
  if (urlEl && desc) {
    urlEl.innerText = desc;
  }

  const uptimeEl = reportEl.querySelector(".statusUptime");
  if (uptimeEl) {
    const uptimeDetail = key === "latency"
      ? (uptimeData.avgDuration !== null ? `Average: ${uptimeData.avgDuration.toFixed(1)}s` : "Average: --") + ` (${uptimeData.coveredLabel})`
      : `${uptimeData.upTime} uptime (${uptimeData.coveredLabel})`;

    uptimeEl.innerText =
      formatDurationText(uptimeData.latestDuration) +
      "  •  " +
      uptimeDetail;
  }

  reportEl.querySelectorAll(".statusSquare").forEach((square) => {
    const relSlot = parseInt(square.dataset.slot, 10);
    applySquareData(square, uptimeData[relSlot]);
  });
}

// ─── Message Rendering ──────────────────────────────────────────────────
export async function genMessages() {
  const container = document.getElementById("messages");
  if (!container) return;
  container.innerHTML = "";
  
  try {
    const response = await fetch("messages.json?t=" + Date.now());
    if (!response.ok) return;

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
  } catch (err) {
    console.error("Failed to load messages:", err);
  }
}

// ─── Log Fetching and Report Building ──────────────────────────────────
export async function genReportLog(container, key, url, desc) {
  let statusLines = state.rawLogCache[key];
  if (statusLines === undefined) {
    const response = await fetch(CONFIG.logBaseUrl + key + "_report.log?t=" + Date.now());
    statusLines = response.ok ? await response.text() : "";
    state.rawLogCache[key] = statusLines;
  }

  const normalized = normalizeData(statusLines);

  let reportEl = container.querySelector('[data-report-key="' + key + '"]');
  if (reportEl) {
    updateStatusContainer(reportEl, normalized, desc);
  } else {
    reportEl = constructStatusStream(key, url, desc, normalized);
    if (reportEl) container.appendChild(reportEl);
  }

  return normalized;
}

export async function genAllReports() {
  if (state.configCache.length === 0) {
    try {
      const response = await fetch("urls.cfg?t=" + Date.now());
      if (response.ok) {
        const configText = await response.text();
        state.configCache = configText.split("\n").filter((l) => l.includes("="));
      }
    } catch (err) {
      console.error("Failed to load urls.cfg:", err);
      return;
    }
  }

  const reportsEl = document.getElementById("reports");
  if (!reportsEl) return;

  let globalLatestTimestamp = null;
  let allColors = [];

  for (let ii = 0; ii < state.configCache.length; ii++) {
    const parts = state.configCache[ii].split("=");
    if (parts.length < 2) continue;
    const key = parts[0];
    const url = parts[1];
    const desc = parts[2] || "FLAME Console";

    const normalized = await genReportLog(reportsEl, key, url, desc);
    const ts = normalized.latestTimestamp;
    if (ts && (!globalLatestTimestamp || ts > globalLatestTimestamp)) {
      globalLatestTimestamp = ts;
    }
    
    let compColor = "nodata";
    if (key === "latency") {
      compColor = getLatencyColor(normalized.overallDuration);
    } else {
      compColor = getColor(normalized.overallUptime);
    }
    allColors.push(compColor);
  }

  // Update overall badge
  const badgeEl = document.getElementById("overall-status-badge");
  if (badgeEl) {
    let overallColor = "nodata";
    if (allColors.includes("failure")) overallColor = "failure";
    else if (allColors.includes("partial")) overallColor = "partial";
    else if (allColors.includes("success")) overallColor = "success";

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

// ─── Resolution Toggle ─────────────────────────────────────────────────
export function updateWindowLabel() {
  const el = document.getElementById("resolution-window-label");
  if (!el) return;

  const totalMs = CONFIG.maxBlocks * getSlotMs();
  const totalHours = totalMs / 3600000;
  if (totalHours >= 24) {
    el.innerText = "Window: " + (totalHours / 24).toFixed(totalHours % 24 === 0 ? 0 : 1) + " days";
  } else {
    el.innerText = "Window: " + totalHours + " hours";
  }
}

export function initResolutionToggle() {
  const buttons = document.querySelectorAll(".res-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const newRes = btn.dataset.resolution;
      if (newRes === state.currentResolution) return;

      state.currentResolution = newRes;
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

// ─── Auto-Refresh ──────────────────────────────────────────────────────
export function forceRefresh() {
  state.rawLogCache = {};
  state.configCache = [];
  genMessages();
  genAllReports();
}

export function initAutoRefresh() {
  const checkbox = document.getElementById("auto-refresh-checkbox");
  if (!checkbox) return;
  
  const applyAutoRefresh = () => {
    if (state.autoRefreshInterval) {
      clearInterval(state.autoRefreshInterval);
      state.autoRefreshInterval = null;
    }
    if (checkbox.checked) {
      state.autoRefreshInterval = setInterval(() => {
        forceRefresh();
      }, CONFIG.autoRefreshIntervalMs);
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
