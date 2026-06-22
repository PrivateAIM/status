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
    // Replace longer keys first so e.g. "$status" doesn't clobber "$statusDetail".
    const entries = Object.entries(parameters).sort((a, b) => b[0].length - a[0].length);
    for (const [key, val] of entries) {
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

// ─── Key helpers ─────────────────────────────────────────────────────────
export function isNodeKey(key) {
  return key.startsWith("node_");
}

export function getDisplayTitle(key) {
  if (key === "latency") return "E2E Latency";
  if (isNodeKey(key)) return key.slice("node_".length);
  return key;
}

// ─── Rendering and Card Updates ──────────────────────────────────────────
export function formatDurationText(latestDuration) {
  return latestDuration !== null && latestDuration !== undefined
    ? `Latest run: ${latestDuration.toFixed(1)}s`
    : "Latest run: --";
}

// Builds the subtitle detail line for a report card. Node cards and the latency
// card show run latency (up/down is conveyed by colour); every other step shows
// its uptime ratio.
export function getStatusDetail(key, uptimeData) {
  if (key === "latency" || isNodeKey(key)) {
    const avg = uptimeData.avgDuration !== null
      ? `Average: ${uptimeData.avgDuration.toFixed(1)}s`
      : "Average: --";
    return formatDurationText(uptimeData.latestDuration) + "  •  " + avg;
  }
  return formatDurationText(uptimeData.latestDuration) + "  •  " + `${uptimeData.upTime}`;
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

  const container = templatize("statusContainerTemplate", {
    title: getDisplayTitle(key),
    url: url,
    desc: desc,
    color: color,
    status: getStatusText(color),
    statusDetail: getStatusDetail(key, uptimeData),
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
    uptimeEl.innerText = getStatusDetail(key, uptimeData);
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
export async function fetchLog(key) {
  let statusLines = state.rawLogCache[key];
  if (statusLines === undefined) {
    const response = await fetch(CONFIG.logBaseUrl + key + "_report.log?t=" + Date.now());
    statusLines = response.ok ? await response.text() : "";
    state.rawLogCache[key] = statusLines;
  }
  return statusLines;
}

export async function genReportLog(container, key, url, desc) {
  const statusLines = await fetchLog(key);
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
  const reportsEl = document.getElementById("reports");
  if (!reportsEl) return;
  const nodeReportsEl = document.getElementById("node-reports");

  let globalLatestTimestamp = null;
  let nodeColors = [];
  let loginColor = "nodata";
  let nodeReportCount = 0;

  const configList = CONFIG.reports.map(({ key, desc }) => ({
    key,
    url: CONFIG.consoleUrl,
    desc,
  }));

  // Fetch all logs in parallel to optimize page speed
  await Promise.all(configList.map(item => fetchLog(item.key)));

  // Render them sequentially in order (they will instantly retrieve from rawLogCache)
  for (const { key, url, desc } of configList) {
    // Per-node cards render in their own section under the latency box; if the
    // node container is missing they fall back to the main reports container.
    const nodeCard = isNodeKey(key);
    const targetEl = nodeCard && nodeReportsEl ? nodeReportsEl : reportsEl;
    const normalized = await genReportLog(targetEl, key, url, desc);
    const ts = normalized.latestTimestamp;
    if (ts && (!globalLatestTimestamp || ts > globalLatestTimestamp)) {
      globalLatestTimestamp = ts;
    }

    const compColor = key === "latency"
      ? getLatencyColor(normalized.overallDuration)
      : getColor(normalized.overallUptime);

    if (nodeCard) {
      nodeReportCount++;
      nodeColors.push(compColor);  // node verdicts drive the overall badge
      continue;
    }
    if (key === "login") loginColor = compColor;
  }

  // Reveal the node section only when at least one node report was rendered.
  const nodeSection = document.getElementById("node-section");
  if (nodeSection) {
    nodeSection.style.display = nodeReportCount > 0 ? "" : "none";
  }

  // Overall status aggregates the per-node verdicts, gated by the shared login
  // step: login down → major; all known nodes up → operational; a minority of
  // nodes down (< majorOutageDownRatio) → partial; half or more down → major.
  // nodata / unknown nodes are excluded from the ratio entirely.
  const nodesUp = nodeColors.filter((c) => c === "success").length;
  const nodesDown = nodeColors.filter((c) => c === "failure").length;
  const knownNodes = nodesUp + nodesDown;
  let overallColor;
  if (loginColor === "failure") {
    overallColor = "failure";
  } else if (knownNodes === 0) {
    overallColor = loginColor;
  } else if (nodesDown === 0) {
    overallColor = "success";
  } else if (nodesDown / knownNodes < CONFIG.overall.majorOutageDownRatio) {
    overallColor = "partial";
  } else {
    overallColor = "failure";
  }

  const badgeEl = document.getElementById("overall-status-badge");
  if (badgeEl) {
    badgeEl.className = "overall-badge status-indicator-badge " + overallColor;
    badgeEl.innerText = getStatusText(overallColor);
  }

  const pulseEl = document.querySelector(".pulse-indicator");
  if (pulseEl) {
    pulseEl.className = "pulse-indicator " + overallColor;
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
