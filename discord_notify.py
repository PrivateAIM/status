"""Update one Discord status message and notify only on incident transitions."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from discord_layout import STATUS_TITLE, display_cards, load_config


class DiscordError(Exception):
    def __init__(self, status, code=None):
        # Never include the request URL: it contains the webhook secret.
        super().__init__(f"Discord request failed (HTTP {status}, code {code}).")
        self.status = status
        self.code = code


def webhook_request(webhook_url, method, payload, message_id=None, files=None):
    parts = urlsplit(webhook_url)
    if (
        parts.scheme != "https"
        or parts.netloc not in {"discord.com", "discordapp.com"}
        or not re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d+/[\w-]+/?", parts.path)
    ):
        raise ValueError("DISCORD_WEBHOOK_URL must be a Discord HTTPS webhook URL.")
    path = parts.path.rstrip("/")
    if message_id:
        if not re.fullmatch(r"\d+", str(message_id)):
            raise ValueError("Invalid saved Discord message ID.")
        path += f"/messages/{message_id}"
    query = dict(parse_qsl(parts.query))
    query["wait"] = "true"
    url = urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), ""))
    if method == "DELETE":
        body = None
        content_type = "application/json"
    elif files:
        boundary = "flame-" + uuid.uuid4().hex
        payload = dict(payload, attachments=[{"id": index, "filename": name}
                                            for index, (name, _) in enumerate(files)])
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
                 'Content-Type: application/json\r\n\r\n'.encode() + json.dumps(payload).encode("utf-8")]
        for index, (name, data) in enumerate(files):
            if not re.fullmatch(r"[\w-]+\.png", name):
                raise ValueError("Invalid history image filename.")
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files[{index}]"; '
                         f'filename="{name}"\r\nContent-Type: image/png\r\n\r\n'.encode() + data)
        body = b"\r\n".join(parts) + f"\r\n--{boundary}--\r\n".encode()
        content_type = f"multipart/form-data; boundary={boundary}"
    else:
        body = json.dumps(payload).encode("utf-8")
        content_type = "application/json"
    request = Request(url, data=body, method=method,
                      headers={"Content-Type": content_type, "User-Agent": "FLAME-Status/1.0"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=15) as response:
                content = response.read()
                return json.loads(content) if content else {}
        except HTTPError as exc:
            try:
                body = json.loads(exc.read())
            except (ValueError, UnicodeError):
                body = {}
            if not isinstance(body, dict):
                body = {}
            if exc.code == 429 and attempt < 2:
                delay = float(body.get("retry_after", 1))
                if 0 <= delay <= 10:
                    time.sleep(delay)
                    continue
            raise DiscordError(exc.code, body.get("code")) from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError("Could not reach Discord; notification state was retained.") from None


def overall_status(statuses):
    if statuses.get("check_runner") == "failed" or statuses.get("login") == "failed":
        return "Major outage", 0xEF4444
    nodes = [value for key, value in statuses.items() if key.startswith("node_")]
    known = [value for value in nodes if value in {"success", "failed"}]
    down = known.count("failed")
    if down:
        return ("Major outage", 0xEF4444) if down / len(known) >= 0.5 else ("Partial outage", 0xF59E0B)
    if "failed" in statuses.values():
        return "Degraded", 0xF59E0B
    if known or statuses.get("login") == "success":
        return "Operational", 0x10B981
    return "No data", 0x64748B


def status_payload(report, dashboard_url, run_url, config=None):
    statuses = report["statuses"]
    cards = display_cards(report, config if config is not None else load_config())
    title, color = overall_status(statuses)
    symbols = {"success": "OK", "failed": "FAILED", "unknown": "No data"}
    fields = []
    for node_group, label in ((False, "Pipeline"), (True, "Nodes")):
        lines = []
        for card in cards:
            if card["key"].startswith("node_") != node_group:
                continue
            name, value, duration = card["title"], card["status"], card["duration"]
            timing = f" ({duration:.1f}s)" if duration is not None else ""
            lines.append(f"**{name}**: {symbols.get(value, 'No data')}{timing}")
        if lines:
            fields.append({"name": label, "value": "\n".join(lines)[:1024], "inline": False})
    links = []
    if dashboard_url:
        links.append(f"[Status dashboard]({dashboard_url})")
    if run_url:
        links.append(f"[Health-check run]({run_url})")
    embed = {
        "title": f"{STATUS_TITLE}: {title}", "color": color,
        "description": " · ".join(links) or "Automated end-to-end health check",
        "timestamp": report["checked_at"], "fields": fields,
        "footer": {"text": "Last health check · scheduled every 30 minutes"},
    }
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def mention_ids(value, label):
    ids = list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    if len(ids) > 100 or any(not re.fullmatch(r"\d+", item) for item in ids):
        raise ValueError(f"{label} must contain up to 100 comma-separated numeric IDs.")
    return ids


def notify(report, webhook_url, state_path, dashboard_url="", run_url="", role_id="", history_images=None,
           config=None, user_ids="", role_ids=""):
    config = config if config is not None else load_config()
    users = mention_ids(user_ids, "DISCORD_ALERT_USER_IDS")
    roles = mention_ids(",".join(filter(None, [role_id, role_ids])), "DISCORD_ALERT_ROLE_IDS")
    path = Path(state_path)
    # Fail safely on malformed state rather than creating duplicate messages.
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(state, dict) or not isinstance(state.get("confirmed_statuses", {}), dict):
        raise ValueError("Invalid Discord notification state.")
    webhook_key = hashlib.sha256(webhook_url.encode()).hexdigest()
    if state.get("webhook_key") != webhook_key:
        state = {"webhook_key": webhook_key}

    payload = status_payload(report, dashboard_url, run_url, config)
    # On edits, clear old images even when rendering falls back to text.
    payload["attachments"] = []
    if history_images:
        for index, (name, _) in enumerate(history_images):
            if index == 0:
                embed = payload["embeds"][0]
                # The cards contain current statuses, durations and history.
                embed["fields"] = []
            else:
                embed = {"color": payload["embeds"][0]["color"]}
                payload["embeds"].append(embed)
            embed["image"] = {"url": f"attachment://{name}"}
    file_options = {"files": history_images} if history_images else {}
    message_id = state.get("message_id")
    if message_id:
        try:
            webhook_request(webhook_url, "PATCH", payload, message_id, **file_options)
        except DiscordError as exc:
            if exc.status != 404 or exc.code != 10008:  # Unknown Message, not Unknown Webhook
                raise
            message_id = None
    if not message_id:
        message_id = webhook_request(webhook_url, "POST", payload, **file_options)["id"]
    state["message_id"] = message_id
    # Save the status message ID even if posting the separate alert fails.
    save_state(path, state)

    excluded = set(config["alert_exclude"])
    previous = {key: value for key, value in state.get("confirmed_statuses", {}).items() if key not in excluded}
    confirmed = dict(previous)
    confirmed.update({key: value for key, value in report["statuses"].items()
                      if key not in excluded and value in {"success", "failed"}})
    old_failures = {key for key, value in previous.items() if value == "failed"}
    failures = {key for key, value in confirmed.items() if value == "failed"}
    new_failures = failures - old_failures
    recovery = bool(old_failures) and not failures
    if new_failures or recovery:
        alert = status_payload(report, dashboard_url, run_url, config)
        alert["embeds"][0]["title"] = f"{STATUS_TITLE}: {'Recovered' if recovery else 'Alert'}"
        if new_failures:
            names = ", ".join(sorted(new_failures))
            alert["content"] = f"{STATUS_TITLE}: check failed: {names}."[:1900]
            mentions = [f"<@&{value}>" for value in roles] + [f"<@{value}>" for value in users]
            if mentions:
                alert["content"] = " ".join(mentions) + " " + alert["content"]
            if roles:
                alert["allowed_mentions"]["roles"] = roles
            if users:
                alert["allowed_mentions"]["users"] = users
            if len(alert["content"]) > 2000:
                raise ValueError("Too many alert mentions for Discord's message limit.")
        else:
            alert["content"] = "All previously alerting Staging E2E checks have recovered."
        old_notification = state.get("notification_id")
        if old_notification:
            if old_notification == state["message_id"]:
                raise ValueError("Notification ID must differ from the persistent status message ID.")
            try:
                webhook_request(webhook_url, "DELETE", {}, old_notification)
            except DiscordError as exc:
                if exc.status != 404 or exc.code != 10008:
                    # Do not post more messages while cleanup is failing. The
                    # unchanged confirmed statuses will retry on the next run.
                    raise
            state.pop("notification_id")
            save_state(path, state)
        state["notification_id"] = webhook_request(webhook_url, "POST", alert)["id"]
    # Unknown results never clear an incident; only explicit success can do so.
    state["confirmed_statuses"] = confirmed
    save_state(path, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="health-check.json")
    parser.add_argument("--state", default="data-branch/discord/state.json")
    parser.add_argument("--check-outcome", default="success")
    parser.add_argument("--logs", default="docs/logs")
    parser.add_argument("--config", help="Discord layout and alert policy JSON (defaults to discord_config.json)")
    args = parser.parse_args()
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("Discord notifications disabled: DISCORD_WEBHOOK_URL is not configured.")
        return 0
    try:
        config = load_config(args.config)
        report_path = Path(args.report)
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {
            "checked_at": datetime.now(timezone.utc).isoformat(), "statuses": {}, "durations": {},
        }
        report["statuses"]["check_runner"] = (
            "failed" if args.check_outcome != "success" and not any(
                value == "failed" for value in report["statuses"].values()
            ) else "success"
        )
        if not report_path.exists():
            report["statuses"]["check_runner"] = "failed"
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        try:
            from discord_history import render_history
            history_images = render_history(report, args.logs, config)
        except (ImportError, OSError, ValueError):
            print("History images unavailable; sending text status instead.")
            history_images = None
        notify(report, webhook_url, args.state,
               dashboard_url=os.environ.get("DISCORD_STATUS_PAGE_URL", ""),
               run_url=f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else "",
               role_id=os.environ.get("DISCORD_ALERT_ROLE_ID", "").strip(),
               role_ids=os.environ.get("DISCORD_ALERT_ROLE_IDS", "").strip(),
               user_ids=os.environ.get("DISCORD_ALERT_USER_IDS", "").strip(),
               history_images=history_images, config=config)
    except (OSError, ValueError, KeyError, TypeError, DiscordError, RuntimeError):
        # Do not print arbitrary exception bodies, which could contain secrets.
        print("Discord notification failed. Check webhook permissions/configuration and saved state.", file=sys.stderr)
        return 1
    print("Discord status updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
