"""Render the status-page history as Discord image attachments."""

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from discord_layout import STATUS_TITLE, combine_entries, display_cards, load_config

BLOCKS = 30
SLOT_SECONDS = 15 * 60
COLORS = {"success": "#10b981", "failure": "#ef4444", "partial": "#f59e0b", "nodata": "#cbd5e1"}


def status_color(status, duration, key):
    if status in {"failed", "failure"}:
        return "failure"
    if status not in {"success", "partial"}:
        return "nodata"
    if key == "latency":
        if duration is None:
            return "partial" if status == "partial" else "nodata"
        if duration >= 300:
            return "failure"
        if duration >= 160:
            return "partial"
    return status


def read_entries(log_dir, key):
    if not re.fullmatch(r"[\w-]+", key):
        raise ValueError("Invalid report key.")
    path = Path(log_dir) / f"{key}_report.log"
    if not path.exists():
        return []
    entries = []
    for row in csv.reader(path.read_text(encoding="utf-8").splitlines()):
        try:
            timestamp = datetime.strptime(row[0].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            status = row[1].strip()
            duration = float(row[2]) if len(row) > 2 and row[2].strip() else None
            entries.append((timestamp, status, duration))
        except (ValueError, IndexError):
            continue
    return entries


def history_data(entries, now, key):
    slots = [[] for _ in range(BLOCKS)]
    anchor = int(now.timestamp() // SLOT_SECONDS)
    for timestamp, status, duration in entries:
        slot = anchor - int(timestamp.timestamp() // SLOT_SECONDS)
        if timestamp <= now and 0 <= slot < BLOCKS:
            slots[BLOCKS - 1 - slot].append((status, duration))
    colors = []
    known = success = total = 0
    for slot in slots:
        valid = [status for status, _ in slot if status in {"success", "partial", "failed", "failure"}]
        passed = valid.count("success")
        total += len(slot)
        known += len(valid)
        success += passed
        run_colors = [status_color(status, duration, key) for status, duration in slot]
        if "failure" in run_colors:
            # Preserve the worst run, including latency spikes, after recovery.
            color = "failure"
        elif "partial" in run_colors or ("success" in run_colors and "nodata" in run_colors):
            color = "partial"
        else:
            color = "success" if "success" in run_colors else "nodata"
        colors.append(color)
    return {
        "colors": colors,
        "uptime": success / known if known else None,
        "strict_uptime": success / total if total else None,
    }


def font(size, bold=False):
    from PIL import ImageFont

    for name in (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        f"C:/Windows/Fonts/{'arialbd' if bold else 'arial'}.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def fire_emoji(size):
    from PIL import Image, ImageDraw, ImageFont

    for name in ("C:/Windows/Fonts/seguiemj.ttf", "NotoColorEmoji.ttf",
                 "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"):
        try:
            # Noto Color Emoji provides a fixed 109px strike; render at its
            # native size, then fit the glyph beside the heading.
            emoji_font = ImageFont.truetype(name, 109)
            break
        except OSError:
            continue
    else:
        raise OSError("Install a system emoji font to render the history heading.")
    # Color glyphs can extend above their font's reported origin. Leave room
    # on every side before cropping to the actual painted pixels.
    emoji = Image.new("RGBA", (512, 512))
    ImageDraw.Draw(emoji).text((128, 128), "🔥", font=emoji_font, embedded_color=True)
    emoji = emoji.crop(emoji.getbbox())
    emoji.thumbnail((size, size), Image.Resampling.LANCZOS)
    return emoji


def render_history(report, log_dir="docs/logs", config=None, *, preview=False):
    from PIL import Image, ImageDraw

    config = config if config is not None else load_config()
    now = datetime.fromisoformat(report["checked_at"].replace("Z", "+00:00"))
    cards = display_cards(report, config)
    scale = config.get("image_scale", 2)
    image = Image.new("RGB", (1000 * scale, (132 + 160 * len(cards)) * scale), "#f8fafc")
    draw = ImageDraw.Draw(image)

    def position(*values):
        return tuple(value * scale for value in values)

    def text(xy, value, size, bold=False, **options):
        draw.text(position(*xy), value, font=font(size * scale, bold), **options)

    def rectangle(box, radius, **options):
        draw.rounded_rectangle(position(*box), radius=radius * scale, width=scale, **options)

    # Draw every glyph and block at the target resolution, rather than upscaling.
    emoji = fire_emoji(30 * scale)
    image.paste(emoji, (28 * scale, 22 * scale), emoji)
    text((68, 20), STATUS_TITLE, 26, True, fill="#0f172a")
    subtitle = "SAMPLE DATA | Last 7.5 hours | 15-minute blocks" if preview else (
        "Last 7.5 hours | 15-minute blocks | oldest to newest"
    )
    text((28, 58), subtitle, 19, fill="#64748b")
    for index, card in enumerate(cards):
        key = card["key"]
        top = 100 + index * 160
        rectangle((12, top, 988, top + 146), 18, fill="#ffffff", outline="#e2e8f0")
        status, duration = card["status"], card["duration"]
        histories = []
        for source in card["checks"]:
            entries = read_entries(log_dir, source)
            minute = now.replace(second=0, microsecond=0)
            source_status = report["statuses"].get(source, "unknown")
            source_duration = report.get("durations", {}).get(source)
            if not any(timestamp == minute and value == source_status for timestamp, value, _ in entries):
                entries.append((minute, source_status, source_duration))
            histories.append(entries)
        history = history_data(combine_entries(histories), now,
                               "latency" if card["checks"] == ["latency"] else key)
        text((32, top + 19), card["title"], 25, True, fill="#0f172a")
        text((32, top + 56), card.get("description", ""), 18, fill="#475569")
        color = status_color(status, duration, "latency" if card["checks"] == ["latency"] else key)
        label = {"success": "OPERATIONAL", "failure": "FAILED", "partial": "PARTIAL"}.get(color, "NO DATA AVAILABLE")
        badge_width = draw.textlength(label, font=font(16 * scale, True)) / scale + 24
        left = 968 - badge_width
        rectangle((left, top + 16, 968, top + 46), 15,
                  fill={"success": "#ecfdf5", "partial": "#fffbeb", "failure": "#fef2f2", "nodata": "#f1f5f9"}[color])
        text((left + 12, top + 21), label, 16, True,
             fill=COLORS[color] if color != "nodata" else "#475569")
        latest = f"{duration:.1f}s" if duration is not None else "--"
        percent = lambda value: f"{value:.2%}" if value is not None else "--%"
        detail = f"Latest: {latest} | Uptime: {percent(history['uptime'])} ({percent(history['strict_uptime'])})"
        text((968, top + 60), detail, 16, fill="#64748b", anchor="ra")
        for block, block_color in enumerate(history["colors"]):
            left = 32 + block * 31.3
            rectangle((left, top + 94, left + 26, top + 128), 5, fill=COLORS[block_color])
    baseline = 100 + 160 * len(cards)
    text((28, baseline + 3), "Green: all OK   Amber: partial / slow   Red: failed   Gray: no data", 16, fill="#475569")
    output = io.BytesIO()
    image.save(output, "PNG", optimize=True)
    return [("flame-history.png", output.getvalue())]
