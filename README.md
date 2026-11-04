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
(status merged, duration averaged). The per-node cards at the bottom show each node's own up/down
and latency; `aggregator-1` counts as up if any of its pairs succeeds. The **overall** badge is the
aggregation of the node verdicts: all up → operational, some down → partial, all down or `login`
failing → major outage.

All work until the next step starts belongs to the current step. In particular, permission errors
during shared project preparation or master image lookup fail `login`; `upload` and later steps
remain `unknown`. The login duration includes this shared setup.

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

The health-check workflow can maintain one Discord status message and post separate incident
and recovery notifications. No running bot service is needed; Pillow renders history images.
The message and image heading are **🔥 Staging E2E Status**. The image uses the system's
regular emoji font; the workflow installs `fonts-noto-color-emoji` on Linux. For local
rendering on Debian/Ubuntu, install it with `sudo apt install fonts-noto-color-emoji`.

1. Create an incoming webhook in the desired Discord channel (channel settings, Integrations,
   Webhooks) and copy its URL.
2. Add `DISCORD_WEBHOOK_URL` as a secret in the **FLAME Health Check** GitHub environment
   (the same environment as the Hub credentials). Without it, Discord delivery is skipped.
3. Optionally set environment variables under GitHub **Settings > Environments > FLAME Health
   Check > Environment variables**:
   - `DISCORD_ALERT_ROLE_ID`: numeric Discord role ID to mention on new failures. The role
     must be mentionable or the webhook must have the relevant permission. Recovery and
     routine updates do not mention the role.
   - `DISCORD_ALERT_ROLE_IDS`: comma-separated role IDs for multiple teams/roles, such as
     `123456789012345678,234567890123456789`. This also works alongside `DISCORD_ALERT_ROLE_ID`.
   - `DISCORD_ALERT_USER_IDS`: comma-separated user IDs for individual people, such as
     `345678901234567890,456789012345678901`.
   - `DISCORD_STATUS_PAGE_URL`: public dashboard URL to include alongside the Actions run link.
4. Run the workflow manually once to create the status message; you can pin it in Discord.

Each subsequent run edits that same message with pipeline and node history cards, durations,
and the check timestamp. Cards show **30 half-hour blocks (15 hours)** from the existing
`docs/logs` files, oldest on the left and newest on the right. Green means success, amber
means slow latency, red means any failure, and gray means no data. A failed run makes its
entire history block red, even if other runs in that block succeeded. The two uptime
percentages cover that window: successful runs divided by known results, then successful
runs divided by all recorded results including unknowns. Empty time slots remain gray and
do not count as recorded runs. Latency blocks use the dashboard's 160s/300s thresholds.
All cards are included in **one high-resolution PNG** (2000 pixels wide by default);
editing the message replaces the old attachment. Open it at full resolution to inspect the
history. If rendering is unavailable, delivery
falls back to the text summary and clears stale images. Alerts keep their text summaries.

A new failure posts one alert, including on the first run if already
unhealthy. The same continuing failure does not post reminders. Additional failing checks
produce another alert; a recovery message is sent only after all previously failing checks
explicitly pass. Unknown/skipped results never clear an incident. Latency failures remain
visible in the status message but **do not trigger alerts or recovery messages by default**.
The 30-minute health-check schedule determines detection time.

**Only the latest incident/recovery notification is retained.** Before posting a new one,
the notifier deletes its previous notification, keeping the persistent status message intact.
If cleanup fails, it retries next run without posting more notifications. A manually deleted
notification is treated as already cleaned up. Older messages created before notification IDs
were tracked need one-time manual deletion.

Discord teams can be represented by server roles. Enable Discord **Developer Mode** under
Settings > Advanced, then use **Copy User ID** or **Copy Role ID** for the intended recipients.
Only configured users/roles are mentioned, only on new failures; recovery/status updates
do not ping anyone. Discord notification settings and role permissions determine delivery.

### Discord layout and alert configuration

Edit [`discord_config.json`](discord_config.json) to customize the message. The default
image contains exactly three cards: **Login + Upload + Distribute**, **Execute + Results**, and
**E2E Latency**. Nodes and runner checks do not add rows; their failures can still
trigger alerts. Missing results remain visible as no data. The underlying health-check steps and dashboard
logs stay separate. A combined card succeeds only when every member succeeds, fails if any
member fails, and otherwise shows no data. Its duration is the sum of its members when all
durations are available. Historical entries are combined per run before building the bars.

- `cards`: ordered groups with `key`, `title`, `checks`, and optional `description`.
  Rearrange or combine checks here, for example `"checks": ["execute", "results"]`.
- `show_nodes`: include node history cards (`false` by default).
- `show_runner`: add a runner failure card (`false` by default).
- `image_scale`: rendering resolution multiplier, from `1` to `4` (default `2`, giving a
  2000-pixel-wide image). Text and bars are drawn at this resolution, without upscaling.
- `alert_exclude`: raw check keys excluded from incident and recovery decisions.
  The default is `["latency"]`. Set it to `[]` to enable latency alerts, or add other keys
  such as `"upload"` or `"node_default-2"` to silence them. Excluded checks remain visible.

The workflow reads this file automatically. Locally, pass `--config path/to/config.json`
to `discord_notify.py` to use another configuration. Presentation grouping does not combine
alert identities: alerts still name the original failed check, such as `distribute`.

`discord_notify.py` reads the current `health-check.json` snapshot generated by `reporting.py`.
The workflow runs delivery even if the check fails; a missing snapshot is reported as a
health-check runner failure. Discord delivery failures do not stop health log publication.

The persistent message ID, latest notification ID, and confirmed statuses live in
`discord/state.json` on the `data` branch and
are committed with the logs. The webhook URL/token are never written there. Deleting that
state intentionally creates a new message and resets alert history. Deleting just the Discord
message causes the next run to recreate it while preserving alert history. Changing the
webhook URL starts a new message/history for that webhook.

After installing `requirements.txt`, run notification tests without credentials or network access:

```bash
python -m unittest discover -s tests -v
```

## Credits

Frontend and status-page concept forked from [statsig-io/statuspage](https://github.com/statsig-io/statuspage).
