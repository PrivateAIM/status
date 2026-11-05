import io
import os
import tempfile
import unittest
from itertools import count
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Aggregation tests do not contact the Hub.
with patch.dict(os.environ, FLAME_USERNAME="test", FLAME_PASSWORD="test"):
    from aggregate import init_tracking, merge_records, merge_step_status

from discord_history import COLORS, history_data, render_history
from discord_layout import combine, load_config
from discord_notify import notify


class PartialStatusTests(unittest.TestCase):
    def test_expected_pair_coverage(self):
        for values, expected in [
            ([], "unknown"), (["unknown", "unknown"], "unknown"),
            (["success", "success"], "success"),
            (["success", "failed"], "partial"),
            (["success", "unknown"], "partial"),
            (["failed", "unknown"], "failed"),
            (["failed", "failed"], "failed"),
        ]:
            with self.subTest(values=values):
                self.assertEqual(merge_step_status(values), expected)

    def test_execution_failure_and_skipped_results(self):
        statuses, durations = init_tracking()
        records = []
        for name, success in [("default-1", False), ("default-2", True)]:
            steps = dict(upload="success", distribute="success",
                         execute="success" if success else "failed",
                         results="success" if success else "unknown",
                         latency="success" if success else "unknown")
            records.append(dict(compute_name=name, success=success, latency=100 if success else None,
                                step_status=steps, step_duration={key: 1 if value == "success" else None
                                                                 for key, value in steps.items()}))
        merge_records(records, SimpleNamespace(name="aggregator-1"), statuses, durations)
        self.assertEqual(statuses["execute"], "partial")
        self.assertEqual(statuses["results"], "partial")
        self.assertEqual(combine([(statuses[key], durations[key]) for key in ("execute", "results")])[0], "partial")
        merge_records(records[1:], SimpleNamespace(name="aggregator-1"), statuses, durations)
        self.assertEqual(statuses["upload"], "partial")  # Missing expected node.

    def test_history_preserves_worst_run(self):
        now = datetime(2026, 11, 5, 10, 27, tzinfo=timezone.utc)
        for statuses, expected in [(["partial", "success"], "partial"),
                                   (["failed", "success"], "failure"),
                                   (["unknown", "success"], "partial"),
                                   (["unknown"], "nodata"), (["success"], "success")]:
            entries = [(now - timedelta(minutes=index), status, 1) for index, status in enumerate(statuses)]
            self.assertEqual(history_data(entries, now, "execute_results")["colors"][-1], expected)
        entries = [(now, "success", 30), (now - timedelta(minutes=1), "success", 400)]
        self.assertEqual(history_data(entries, now, "latency")["colors"][-1], "failure")
        history = history_data([(now, "partial", 1)], now, "results")
        self.assertEqual(history["uptime"], 0)

    def test_history_uses_same_fixed_intervals_as_dashboard(self):
        now = datetime(2026, 11, 5, 13, 55, tzinfo=timezone.utc)
        entries = [(now.replace(minute=28), "partial", 0.68),
                   (now.replace(minute=42), "success", 1.15),
                   (now, "success", 0.77)]
        colors = history_data(entries, now, "results")["colors"]
        self.assertEqual(colors[-1], "success")
        self.assertEqual(colors[-2], "partial")

    def test_partial_image_badge_and_history_are_amber(self):
        from PIL import Image
        report = dict(checked_at="2026-11-05T10:27:00+00:00",
                      statuses=dict(execute="partial", results="partial"),
                      durations=dict(execute=135.85, results=0.57))
        config = dict(cards=[card for card in load_config()["cards"] if card["key"] == "execute_results"],
                      show_nodes=False, show_runner=False, image_scale=1)
        with tempfile.TemporaryDirectory() as directory:
            data = render_history(report, directory, config)[0][1]
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.getpixel((950, 130)), (255, 251, 235))  # Amber badge background.
        self.assertEqual(image.getpixel((950, 210)), (245, 158, 11))  # Latest history block.

    def test_partial_does_not_send_all_clear(self):
        config = load_config()
        def report(status):
            return dict(checked_at="2026-11-05T10:27:00+00:00",
                        statuses=dict(login="success", execute=status, results=status), durations={})
        with tempfile.TemporaryDirectory() as directory, patch('discord_notify.webhook_request') as request:
            ids = count(123)
            request.side_effect = lambda *args, **kwargs: {"id": str(next(ids))}
            state = Path(directory) / "state.json"
            notify(report("failed"), "test-webhook", state, config=config)
            request.reset_mock()
            notify(report("partial"), "test-webhook", state, config=config)
            self.assertEqual([call.args[1] for call in request.call_args_list], ["PATCH", "PATCH"])
            request.reset_mock()
            notify(report("success"), "test-webhook", state, config=config)
            self.assertEqual([call.args[1] for call in request.call_args_list], ["PATCH", "DELETE", "POST"])
            self.assertIn("recovered", request.call_args.args[2]["content"])


if __name__ == "__main__":
    unittest.main()
