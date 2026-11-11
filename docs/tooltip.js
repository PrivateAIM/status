import { formatSlotDate } from "./data.js";
import { getStatusText, getStatusDescriptiveText } from "./constants.js";

function hasTooltipSelection() {
  const selection = window.getSelection();
  const tooltip = document.getElementById("tooltip");
  return selection && !selection.isCollapsed && tooltip &&
    (tooltip.contains(selection.anchorNode) || tooltip.contains(selection.focusNode));
}

export function formatCheckTimes(firstTimestamp, lastTimestamp) {
  if (!firstTimestamp || !lastTimestamp) return "No recorded checks";
  const first = formatSlotDate(new Date(Number(firstTimestamp)));
  const last = formatSlotDate(new Date(Number(lastTimestamp)));
  return firstTimestamp === lastTimestamp ? `Check: ${last}` : `Checks: ${first} – ${last}`;
}

let activeSquare = null;
let initialized = false;

export function closeTooltip(restoreFocus = false) {
  const square = activeSquare;
  if (square) square.setAttribute("aria-expanded", "false");
  const tooltip = document.getElementById("tooltip");
  if (tooltip) {
    tooltip.classList.remove("is-visible");
    tooltip.setAttribute("aria-hidden", "true");
    tooltip.inert = true;
  }
  if (restoreFocus && square) square.focus({ preventScroll: true });
  activeSquare = null;
}

export function initTooltip() {
  if (initialized) return;
  initialized = true;
  document.getElementById("tooltipClose")?.addEventListener("click", () => closeTooltip(true));
  document.addEventListener("click", (event) => {
    if (!event.target.closest("#tooltip, .statusSquare")) closeTooltip();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeTooltip(true);
  });
  document.addEventListener("focusin", (event) => {
    if (activeSquare && !event.target.closest("#tooltip") && event.target !== activeSquare) closeTooltip();
  });
  window.addEventListener("resize", () => closeTooltip());
}

function renderRuns(entries) {
  const list = document.getElementById("tooltipRuns");
  if (!list) return;
  list.replaceChildren();
  if (!entries.length) {
    const item = document.createElement("li");
    item.textContent = "No checks in this time window.";
    list.appendChild(item);
  }
  for (const entry of entries) {
    const item = document.createElement("li");
    const label = new Date(entry.timestamp).toLocaleString();
    // Only turn GitHub Actions URLs into links; log contents are never HTML.
    let url = null;
    try {
      const candidate = new URL(entry.runUrl);
      if (candidate.protocol === "https:" && candidate.hostname === "github.com" &&
          /^\/[^/]+\/[^/]+\/actions\/runs\/\d+(?:\/attempts\/\d+)?$/.test(candidate.pathname)) {
        url = candidate.href;
      }
    } catch { /* Older rows and local checks have no URL. */ }
    const title = document.createElement(url ? "a" : "span");
    title.textContent = url ? `${label} - View run` : label;
    if (url) {
      title.href = url;
      title.target = "_blank";
      title.rel = "noopener noreferrer";
      title.setAttribute("aria-label", `Open GitHub Actions run for ${label}`);
    }
    const meta = document.createElement("span");
    meta.className = "tooltip-run-meta";
    const result = entry.result === 1 ? "Passed" : entry.result === 0 ? "Failed" : entry.result === 0.5 ? "Partial" : "Unknown / skipped";
    meta.textContent = result + (entry.duration !== null ? ` - ${entry.duration.toFixed(1)}s` : "") +
      (url ? "" : " - Run link unavailable");
    item.append(title, meta);
    list.appendChild(item);
  }
}

export function showTooltip(element, key, color, duration) {
  const toolTipDiv = document.getElementById("tooltip");
  if (!toolTipDiv) return;

  const dateTimeEl = document.getElementById("tooltipDateTime");
  if (dateTimeEl) dateTimeEl.innerText = formatCheckTimes(element.dataset.firstTimestamp, element.dataset.lastTimestamp);

  let descText = getStatusDescriptiveText(color);
  if (duration !== null && duration !== undefined && (color === "success" || color === "partial")) {
    descText += `\nAverage run duration: ${duration.toFixed(1)}s.`;
  }
  const descEl = document.getElementById("tooltipDescription");
  if (descEl) descEl.innerText = descText;

  const statusDiv = document.getElementById("tooltipStatus");
  if (statusDiv) {
    statusDiv.innerText = getStatusText(color);
    statusDiv.className = "tooltipStatus " + color;
  }

  const details = document.getElementById("tooltipRunDetails");
  if (details) details.hidden = false;
  toolTipDiv.setAttribute("role", "dialog");
  toolTipDiv.setAttribute("aria-label", "Status and contributing checks");
  toolTipDiv.setAttribute("aria-hidden", "false");
  toolTipDiv.inert = false;
  renderRuns(element.reportEntries || []);

  const rect = element.getBoundingClientRect();
  const tooltipWidth = toolTipDiv.offsetWidth;

  // Center the tooltip on the square, but clamp it to the viewport so it
  // doesn't overflow off-screen on narrow/mobile viewports.
  const margin = 8;
  const viewportWidth = document.documentElement.clientWidth;
  const idealLeft = rect.left + window.scrollX + rect.width / 2 - tooltipWidth / 2;
  const minLeft = window.scrollX + margin;
  const maxLeft = window.scrollX + viewportWidth - tooltipWidth - margin;
  const left = Math.min(Math.max(idealLeft, minLeft), maxLeft);

  const above = rect.bottom + 10 + toolTipDiv.offsetHeight > window.innerHeight &&
    rect.top > toolTipDiv.offsetHeight + 10;
  toolTipDiv.classList.toggle("above", above);
  toolTipDiv.style.top = (above
    ? rect.top + window.scrollY - toolTipDiv.offsetHeight - 10
    : rect.bottom + window.scrollY + 10) + "px";
  toolTipDiv.style.left = left + "px";

  // Re-point the arrow at the square's center, since the tooltip box may
  // have been shifted away from being centered on it.
  const squareCenter = rect.left + window.scrollX + rect.width / 2;
  const arrow = document.getElementById("tooltipArrow");
  if (arrow) {
    arrow.style.left = Math.min(Math.max(squareCenter - left, 12), tooltipWidth - 12) + "px";
  }

  toolTipDiv.classList.add("is-visible");
}

export function showTooltipForSquare(square) {
  // Clicking or focusing the hovered square must not rebuild or reposition it.
  if (activeSquare === square || hasTooltipSelection()) return;
  closeTooltip();
  activeSquare = square;
  square.setAttribute("aria-expanded", "true");
  const key = square.dataset.key;
  const color = square.dataset.status;
  const duration = square.dataset.duration ? parseFloat(square.dataset.duration) : null;
  showTooltip(square, key, color, duration);
}
