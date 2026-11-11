import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import reporting


class ReportingTests(unittest.TestCase):
    def test_run_attempt_and_legacy_rows_survive_log_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "login_report.log"
            log.write_text("old, success, 1.00\nlegacy, failed, \n", encoding="utf-8")
            env = {
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "example/status",
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "2",
            }
            with patch.dict(os.environ, env, clear=True), patch.object(reporting, "LOG_DIR", directory), patch.object(reporting, "MAX_LOG_LINES", 2):
                reporting.append_log("login", "success", 4.125, "2026-11-11 12:00")
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), [
                "legacy, failed, ",
                "2026-11-11 12:00, success, 4.12, https://github.com/example/status/actions/runs/123/attempts/2",
            ])

    def test_local_checks_have_no_run_link(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(reporting.get_run_url(), "")


if __name__ == "__main__":
    unittest.main()
