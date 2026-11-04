import { initTheme } from "./theme.js";
import { initResolutionToggle, initAutoRefresh, forceRefresh } from "./ui.js";
import { initTooltip } from "./tooltip.js";

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initTooltip();
  initResolutionToggle();
  initAutoRefresh();
  forceRefresh();
});
