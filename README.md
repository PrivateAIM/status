[![Health Check](../../actions/workflows/health-check.yml/badge.svg)](../../actions/workflows/health-check.yml)

# FLAME E2E Status Page

Automated end-to-end health monitoring for the [FLAME](https://privateaim.net) federated learning and analysis platform (staging cluster).

Every 30 minutes, a GitHub Action runs a complete federated analysis round against the FLAME Hub — from login to result retrieval — and publishes the outcome to a static status page via GitHub Pages.

Maintainer: [Jules Kreuer](https://github.com/not-a-feature)

## What is checked

Each run executes [`flame_health_check.py`](flame_health_check.py). After a shared `login`, it
runs a **separate minimal analysis per compute node** — each one pairing the aggregator with a
single node (`aggregator-1 + default-1`, `aggregator-1 + default-2`, …) — **in parallel**, each
gated by an `online` pre-check. This yields an independent up/down verdict and latency for every
node, instead of one all-or-nothing round that hangs if any node is down.

The results are merged into six step cards and a per-node section:

| Check | What it verifies | Timeout |
| --- | --- | --- |
| `login` | Authentication against the FLAME Hub and basic API access (node listing). Shared, once. | 10 s |
| `upload` | Per pair: analysis creation, code bucket provisioning, and upload of the test script ([`flame_checks/00_test_connection.py`](flame_checks/00_test_connection.py)) as entrypoint. | 60 s per wait |
| `distribute` | Per pair: analysis image build and distribution to the paired nodes. | 120 s per phase |
| `execute` | Per pair: execution of the analysis on the paired nodes. | 240 s |
| `results` | Per pair: download of the result tarball and confirmation that both paired nodes reported `ok`. | 60 s |
| `latency` | Per pair: E2E duration stays below the sum of the per-step budgets. | 600 s |

The five pipeline step cards (`upload`…`latency`) are **aggregated across the parallel pair runs**
(status merged, duration averaged). The per-node cards at the bottom show each node's own up/down
and latency; `aggregator-1` counts as up if any of its pairs succeeds. The **overall** badge is the
aggregation of the node verdicts: all up → operational, some down → partial, all down or `login`
failing → major outage.

If a step fails within a pair run, that run's subsequent steps are recorded as `unknown` (shown as
"no data" on the page, excluded from uptime statistics); an offline node is recorded down without
spending a run on it.

Results are appended as `date, status, duration` lines to `docs/logs/<check>_report.log` (capped at 2000 lines, ≈ 40 days at 30-minute intervals) and committed back to the repository. The frontend (`docs/index.html` / `docs/index.js`) renders the last 30 days per check, including run durations.

## Setup

1. **Repository secrets** (Settings → Secrets and variables → Actions):
   - `FLAME_USERNAME` / `FLAME_PASSWORD` — Hub credentials (required).
   The Hub endpoints (`*.staging.privateaim.net`) are hardcoded at the top of `flame_health_check.py`.
2. **GitHub Pages**: Settings → Pages → deploy from the `main` branch, `/docs` folder.
3. Optionally adjust `TARGET_NODE_NAMES` and `PROJECT_NAME` in `flame_health_check.py`, and the report cards / console link in `CONFIG.reports` / `CONFIG.consoleUrl` in `docs/constants.js`.
4. Trigger a first run manually via the *Scheduled Health Check* workflow (`workflow_dispatch`).

## Hub compatibility

`flame-hub-client` is versioned against the Hub API and is **deliberately unpinned**: each
CI run installs the current release. Historically the pin was the problem — it sat still
while the cluster was upgraded, and the check went dark until someone noticed.

Unpinning inverts the risk rather than removing it. The client can now run *ahead* of the
cluster, so when a run fails, compare the two. Both service versions are readable without
credentials:

```bash
curl https://core.staging.privateaim.net/ && curl https://auth.staging.privateaim.net/
```

Known breaks, for reading old logs: Hub `0.12` replaced robots with clients, and Hub `0.13`
renamed every field (and the `filter`/`sort`/`include` query vocabulary) from snake_case to
camelCase and wrapped single-record responses in `{data, meta}`. Client `0.5.x` is the first
release that speaks `0.13`.

A version mismatch rarely fails where you would expect. `login` is the first step that
touches the API, so a model mismatch surfaces there — a fast `login, failed` (about a
second) rather than a timeout. If the mismatch is in a later endpoint instead, `login`
passes and every subsequent step lands on "no data". Either way the traceback is only in
the Actions run log, not on the status page.

## Manual messages

Maintenance or incident notices can be posted by editing [`docs/messages.json`](docs/messages.json) (e.g. directly in the GitHub web editor). Each entry is rendered as a banner above the status cards, newest first:

```json
[
  {
    "date": "2026-06-12",
    "type": "maintenance",
    "title": "Hub upgrade",
    "text": "Staging cluster will be unavailable June 12, 09:00-11:00 CEST."
  }
]
```

`type` controls the banner accent: `info` (blue), `maintenance` (yellow), `incident` (red). Remove entries (or set the file to `[]`) to clear the page.

## Running locally

```bash
pip install -r requirements.txt
export FLAME_USERNAME=... FLAME_PASSWORD=...
python flame_health_check.py
```

## Credits

Frontend and status-page concept forked from [statsig-io/statuspage](https://github.com/statsig-io/statuspage).
