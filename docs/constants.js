export const CONFIG = {
  maxBlocks: 30,
  statusLookbackMinutes: 45,
  logBaseUrl: "https://raw.githubusercontent.com/not-a-feature/FLAME-Status/data/docs/logs/",

  // Console all report cards link to.
  consoleUrl: "https://core.staging.privateaim.net",

  // Report cards in render order. `key` selects the <key>_report.log stream;
  // `node_*` keys render in the per-node availability section.
  reports: [
    { key: "login",             desc: "Authentication & Login" },
    { key: "upload",            desc: "Code Upload" },
    { key: "distribute",        desc: "Distribution to Nodes" },
    { key: "execute",           desc: "Code Execution on Nodes" },
    { key: "results",           desc: "Results Retrieval" },
    { key: "latency",           desc: "E2E Latency" },
    { key: "node_aggregator-1", desc: "Aggregator Node 1" },
    { key: "node_default-1",    desc: "Compute Node 1" },
    { key: "node_default-2",    desc: "Compute Node 2" },
  ],
  
  // Latency thresholds (seconds)
  latency: {
    successThreshold: 160,
    partialThreshold: 300
  },
  
  // Uptime thresholds (ratios)
  uptime: {
    partialThreshold: 0.3
  },

  // Overall badge: fraction of known (non-nodata) nodes that must be DOWN to
  // escalate from partial outage (orange) to major outage (red).
  overall: {
    majorOutageDownRatio: 0.5
  },
  
  // Auto-refresh interval (ms)
  autoRefreshIntervalMs: 60000,
  
  // Resolutions config
  resolutions: {
    "1d":    { ms: 24 * 3600 * 1000, label: "1 day" },
    "6h":    { ms:  6 * 3600 * 1000, label: "6 hours" },
    "30min": { ms:      30 * 60000,  label: "30 min" },
  },
  
  // Theme Assets
  theme: {
    darkLogo: "https://docs.privateaim.net/images/icon/icon_flame_light.png",
    lightLogo: "https://docs.privateaim.net/images/icon/icon_flame_dark.png",
    sunIcon: `<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>`,
    moonIcon: `<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>`
  }
};

export function getStatusText(color) {
  return color === "nodata"
    ? "No Data Available"
    : color === "success"
    ? "Fully Operational"
    : color === "failure"
    ? "Major Outage"
    : color === "partial"
    ? "Partial Outage"
    : "Unknown";
}

export function getStatusDescriptiveText(color) {
  return color === "nodata"
    ? "No Data Available: Health check was not performed."
    : color === "success"
    ? "No downtime recorded in this period."
    : color === "failure"
    ? "Major outages recorded in this period."
    : color === "partial"
    ? "Partial outages recorded in this period."
    : "Unknown";
}
