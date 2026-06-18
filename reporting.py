import os
import time

LOG_DIR = os.path.join("docs", "logs")
MAX_LOG_LINES = 2000


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
    existing_lines.append(f"{date_str}, {status}, {duration_str}\n")

    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(existing_lines)


def write_all_reports(final_statuses: dict[str, str], final_durations: dict[str, float | None]):
    date_str = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    for key in final_statuses.keys():
        duration = final_durations[key]
        append_log(key, final_statuses[key], duration, date_str)
        duration_str = f"{duration:.2f}s" if duration is not None else "n/a"
        print(f"Logged status for {key}: {final_statuses[key]} ({duration_str})")
