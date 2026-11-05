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
| `login` | Authentication, node selection, shared project preparation/cleanup, and master image lookup. Shared, once. | 10 s for authentication and node listing |
| `upload` | Per pair: analysis creation, code bucket provisioning, and upload of the test script ([`flame_checks/00_test_connection.py`](flame_checks/00_test_connection.py)) as entrypoint. | 60 s per wait |
| `distribute` | Per pair: analysis image build and distribution to the paired nodes. | 120 s per phase |
| `execute` | Per pair: execution of the analysis on the paired nodes. | 240 s |
| `results` | Per pair: download of the result tarball and confirmation that both paired nodes reported `ok`. | 60 s |
| `latency` | Per pair: E2E duration stays below the sum of the per-step budgets. | 600 s |

The five pipeline step cards (`upload`…`latency`) are **aggregated across the parallel pair runs**
(status merged, duration averaged). A step is green only when every expected pair passed,
orange when some passed and others failed or were skipped, red when checks ran but none passed,
and gray when no pair reached the step. Missing expected nodes also prevent green.
The per-node cards at the bottom show each node's own up/down
and latency; `aggregator-1` counts as up if any of its pairs succeeds. The **overall** badge is the
aggregation of the node verdicts: all up → operational, some down → partial, all down or `login`
failing → major outage.

All work until the next step starts belongs to the current step. In particular, permission errors
during shared project preparation or master image lookup fail `login`; `upload` and later steps
remain `unknown`. The login duration includes this shared setup.

If a step fails within a pair run, that run's subsequent steps are recorded as `unknown`.
These skipped steps count as incomplete coverage when another pair succeeds. An entirely
unattempted step is shown as "no data" and excluded from uptime statistics. Uptime measures
fully successful runs; partial runs count as known but not fully successful.

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
second) rather than a timeout. A mismatch in a shared setup endpoint also fails `login`;
a mismatch during a pair run fails the active step. The traceback is only in
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

## Discord notifications

Each health check updates one **Staging E2E Status** message with a single history image:

- Login + Upload + Distribute
- Execute + Results
- E2E Latency

The image covers the last 15 hours. If any check in a group fails, that group turns red;
partial checks or mixed success and no data turn it orange. The dashboard and image retain
the worst recorded status in each history block, including latency spikes, after recovery.
Current image badges show the latest run; dashboard badges summarize the last 45 minutes.
New failures send an alert; recovery sends an all-clear. Each notification replaces the
previous one, so the channel keeps just the status message and the latest notification.
Latency alone does not trigger alerts by default.

To set it up:

1. In your Discord channel, open **Settings > Integrations > Webhooks** and create a webhook.
2. Save its URL as `DISCORD_WEBHOOK_URL` in the **FLAME Health Check** GitHub environment secrets.
3. Run the health-check workflow once. You can pin the status message in Discord.

To notify people when the overall status worsens, add either of these GitHub environment variables:

- `DISCORD_ALERT_USER_IDS`: comma-separated user IDs.
- `DISCORD_ALERT_ROLE_IDS`: comma-separated role IDs for teams.

Enable Discord's **Developer Mode** under **Settings > Advanced** to copy user and role IDs.
Each worsening transition pings once. Repeated failures, additional failures at the same
severity, recovery messages, and routine updates do not ping anyone. Optionally set
`DISCORD_STATUS_PAGE_URL` to include your dashboard link.

Edit [`discord_config.json`](discord_config.json) to change the rows, image resolution,
or alert exclusions. `alert_exclude` defaults to `["latency"]`; set it to `[]` to enable
latency alerts. The workflow handles message IDs and notification history automatically.

## Credits

Frontend and status-page concept forked from [statsig-io/statuspage](https://github.com/statsig-io/statuspage).
