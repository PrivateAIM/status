import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discord_layout import load_config
from discord_notify import DiscordError, notify


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / "state.json"
        self.config = load_config()  # Nodes deliberately hidden in the image.
        self.request = patch("discord_notify.webhook_request").start()
        self.addCleanup(patch.stopall)
        self.request.return_value = {"id": "300"}

    def report(self, status="failed", time="2026-11-05T13:28:00+00:00"):
        return dict(checked_at=time, statuses={
            "login": "success", "upload": "success", "distribute": "success",
            "execute": "success" if status == "success" else "partial",
            "results": "success" if status == "success" else "partial",
            "latency": "success", "node_aggregator-1": "success",
            "node_default-1": "success", "node_default-2": status,
        }, durations={})

    def save_existing(self, statuses):
        self.state.write_text(json.dumps(dict(
            webhook_key=hashlib.sha256(b"test-webhook").hexdigest(),
            message_id="100", notification_id="200", confirmed_statuses=statuses,
        )), encoding="utf-8")

    def send(self, report):
        notify(report, "test-webhook", self.state, config=self.config, role_ids="12345")

    def test_existing_notification_refreshed_during_unchanged_outage(self):
        report = self.report()
        self.save_existing(report["statuses"])
        self.send(report)
        self.assertEqual([call.args[1] for call in self.request.call_args_list], ["PATCH", "PATCH"])
        call = self.request.call_args
        self.assertEqual(call.args[3], "200")
        payload = call.args[2]
        self.assertIn("node_default-2", payload["content"])
        self.assertNotIn("recovered", payload["content"].lower())
        embed = payload["embeds"][0]
        self.assertIn("outage", embed["title"].lower())
        nodes = next(field["value"] for field in embed["fields"] if field["name"] == "Nodes")
        self.assertIn("**default-2**: FAILED", nodes)
        self.assertEqual(embed["timestamp"], report["checked_at"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["flags"], 4096)

    def test_missing_result_retains_unresolved_node(self):
        self.save_existing(self.report()["statuses"])
        report = self.report("success")
        report["statuses"]["node_default-2"] = "unknown"
        self.send(report)
        payload = self.request.call_args.args[2]
        self.assertNotIn("recovered", payload["content"].lower())
        self.assertIn("Awaiting a fresh result for: node_default-2", payload["content"])
        self.assertIn("**default-2**: FAILED", str(payload["embeds"][0]["fields"]))

    def test_recovery_requires_node_success_and_stays_current(self):
        self.save_existing(self.report()["statuses"])
        self.send(self.report("success"))
        self.assertEqual([call.args[1] for call in self.request.call_args_list], ["PATCH", "DELETE", "POST"])
        self.assertIn("recovered", self.request.call_args.args[2]["content"])
        self.request.reset_mock()
        report = self.report("success", "2026-11-05T13:57:00+00:00")
        self.send(report)
        self.assertEqual([call.args[1] for call in self.request.call_args_list], ["PATCH", "PATCH"])
        self.assertEqual(self.request.call_args.args[2]["embeds"][0]["timestamp"], report["checked_at"])

    def test_new_outage_replaces_recovery_and_pings(self):
        self.save_existing(self.report("success")["statuses"])
        self.send(self.report())
        self.assertEqual([call.args[1] for call in self.request.call_args_list], ["PATCH", "DELETE", "POST"])
        self.assertIn("<@&12345>", self.request.call_args.args[2]["content"])
        self.assertIn("node_default-2", self.request.call_args.args[2]["content"])

    def test_deleted_notification_recreated_silently(self):
        self.save_existing(self.report()["statuses"])
        self.request.side_effect = [{}, DiscordError(404, 10008), {"id": "300"}]
        self.send(self.report())
        self.assertEqual([call.args[1] for call in self.request.call_args_list], ["PATCH", "PATCH", "POST"])
        self.assertEqual(self.request.call_args.args[2]["flags"], 4096)
        self.assertEqual(json.loads(self.state.read_text())["notification_id"], "300")
