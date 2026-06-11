[![Health Check](../../actions/workflows/health-check.yml/badge.svg)](../../actions/workflows/health-check.yml)

# FLAME E2E Status Page

Automated end-to-end health monitoring for the [FLAME](https://privateaim.net) federated learning and analysis platform (staging cluster).

Every 30 minutes, a GitHub Action runs a complete federated analysis round against the FLAME Hub — from login to result retrieval — and publishes the outcome to a static status page via GitHub Pages.

## What is checked

Each run executes [`flame_health_check.py`](flame_health_check.py), which performs a real E2E workflow and reports six checks:

| Check | What it verifies | Timeout |
| --- | --- | --- |
| `login` | Authentication against the FLAME Hub and basic API access (node listing). | 10 s |
| `upload` | Project/analysis creation, code bucket provisioning, and upload of the test script ([`flame_checks/00_test_connection.py`](flame_checks/00_test_connection.py)) as entrypoint. | 60 s |
| `distribute` | Analysis image build and distribution to the target nodes. | 60 s |
| `execute` | Execution of the analysis on the federated nodes. | 120 s |
| `results` | Download of the result tarball and validation of the aggregated result payload. | — |
| `latency` | Total E2E duration stays below 300 s. | 300 s |

If a step fails, all subsequent steps are recorded as `unknown` (shown as "no data" on the page, excluded from uptime statistics).

Results are appended as `date, status, duration` lines to `docs/logs/<check>_report.log` (capped at 2000 lines, ≈ 40 days at 30-minute intervals) and committed back to the repository. The frontend (`docs/index.html` / `docs/index.js`) renders the last 30 days per check, including run durations.

## Setup

1. **Repository secrets** (Settings → Secrets and variables → Actions):
   - `FLAME_USERNAME` / `FLAME_PASSWORD` — Hub credentials (required).
   The Hub endpoints (`*.staging.privateaim.net`) are hardcoded at the top of `flame_health_check.py`.
2. **GitHub Pages**: Settings → Pages → deploy from the `main` branch, `/docs` folder.
3. Optionally adjust `TARGET_NODE_NAMES` and `PROJECT_NAME` in `flame_health_check.py`, and the display links in `docs/urls.cfg`.
4. Trigger a first run manually via the *Scheduled Health Check* workflow (`workflow_dispatch`).

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
