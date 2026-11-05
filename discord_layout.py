"""Discord presentation and alert policy, independent of the health-check pipeline."""

import json
import re
from pathlib import Path

STATUS_TITLE = "Staging E2E Status"


def load_config(path=None):
    path = Path(path) if path else Path(__file__).with_name("discord_config.json")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("cards"), list):
        raise ValueError("Discord configuration must contain a cards list.")
    keys, checks = set(), set()
    for card in config["cards"]:
        if (
            not isinstance(card, dict)
            or not isinstance(card.get("key"), str)
            or not re.fullmatch(r"[\w-]+", card["key"])
            or card["key"] in keys
            or not isinstance(card.get("title"), str)
            or not isinstance(card.get("description", ""), str)
            or not isinstance(card.get("checks"), list)
            or not card["checks"]
        ):
            raise ValueError("Invalid or duplicate Discord history card.")
        keys.add(card["key"])
        for check in card["checks"]:
            if not isinstance(check, str) or not re.fullmatch(r"[\w-]+", check) or check in checks:
                raise ValueError("Discord checks must appear in only one card.")
            checks.add(check)
    excluded = config.get("alert_exclude", ["latency"])
    if not isinstance(excluded, list) or any(not isinstance(key, str) for key in excluded):
        raise ValueError("alert_exclude must be a list of check keys.")
    config["alert_exclude"] = excluded
    if not isinstance(config.get("show_nodes", True), bool):
        raise ValueError("show_nodes must be true or false.")
    if not isinstance(config.get("show_runner", True), bool):
        raise ValueError("show_runner must be true or false.")
    scale = config.get("image_scale", 2)
    if type(scale) is not int or not 1 <= scale <= 4:
        raise ValueError("image_scale must be an integer between 1 and 4.")
    config["image_scale"] = scale
    return config


def combine(values):
    statuses = [status for status, _ in values]
    status = "failed" if any(value in {"failed", "failure"} for value in statuses) else (
        "partial" if "partial" in statuses or ("success" in statuses and "unknown" in statuses) else
        "success" if statuses and all(value == "success" for value in statuses) else "unknown"
    )
    durations = [duration for _, duration in values]
    duration = sum(durations) if durations and all(value is not None for value in durations) else None
    return status, duration


def display_cards(report, config):
    # Keep configured rows visible as no-data even when a run stops early.
    cards = [dict(card) for card in config["cards"]]
    included = {key for card in cards for key in card["checks"]}
    if config.get("show_nodes", True):
        cards.extend({"key": key, "title": key.removeprefix("node_"), "checks": [key],
                      "description": "Node availability"}
                     for key in report["statuses"] if key.startswith("node_") and key not in included)
    if config.get("show_runner", True) and report["statuses"].get("check_runner") == "failed" and "check_runner" not in included:
        cards.append({"key": "check_runner", "title": "Check runner", "checks": ["check_runner"],
                      "description": "Health-check workflow"})
    for card in cards:
        card["status"], card["duration"] = combine([
            (report["statuses"].get(key, "unknown"), report.get("durations", {}).get(key))
            for key in card["checks"]
        ])
    return cards


def combine_entries(histories):
    # The logs have minute precision. Preserve repeated runs in the same minute
    # by matching the first occurrence in each log, then the second, etc.
    indexed = []
    for entries in histories:
        occurrences = {}
        records = {}
        for timestamp, status, duration in entries:
            index = occurrences.get(timestamp, 0)
            occurrences[timestamp] = index + 1
            records[timestamp, index] = (status, duration)
        indexed.append(records)
    keys = sorted({key for records in indexed for key in records})
    return [(timestamp, *combine([records.get((timestamp, index), ("unknown", None))
                                 for records in indexed])) for timestamp, index in keys]
