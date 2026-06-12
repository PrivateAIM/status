import { initTheme } from "./theme.js";
import { initResolutionToggle, initAutoRefresh, genMessages, genAllReports } from "./ui.js";

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initResolutionToggle();
  initAutoRefresh();
  genMessages();
  genAllReports();
});
