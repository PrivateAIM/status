import os
import time
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = os.path.join("docs", "logs")
MAX_LOG_LINES = 2000


def get_run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not repository or not run_id:
        return ""
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return f"{server}/{repository}/actions/runs/{run_id}/attempts/{attempt}"


def append_log(key: str, status: str, duration: float | None, date_str: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{key}_report.log")

    existing_lines = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    # Keep the most recent lines so the file stays at MAX_LOG_LINES including
    # the new entry appended below.
    existing_lines = existing_lines[-(MAX_LOG_LINES - 1):]
    duration_str = f"{duration:.2f}" if duration is not None else ""
    existing_lines.append(f"{date_str}, {status}, {duration_str}, {get_run_url()}\n")

    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(existing_lines)


def write_all_reports(final_statuses: dict[str, str], final_durations: dict[str, float | None]):
    # A current-run snapshot lets notification delivery run independently, even
    # after the health check exits with an error. It is not restored from data.
    Path("health-check.json").write_text(json.dumps({
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "statuses": final_statuses,
        "durations": final_durations,
    }, indent=2) + "\n", encoding="utf-8")
    date_str = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    for key in final_statuses.keys():
        duration = final_durations[key]
        append_log(key, final_statuses[key], duration, date_str)
        duration_str = f"{duration:.2f}s" if duration is not None else "n/a"
        print(f"Logged status for {key}: {final_statuses[key]} ({duration_str})")
