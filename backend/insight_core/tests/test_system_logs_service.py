import tempfile
import unittest
from pathlib import Path

from insight_core.services.system_logs_service import SystemLogsService


class SystemLogsServiceTests(unittest.TestCase):
    def test_returns_last_lines_from_known_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "core" / "application.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

            service = SystemLogsService(logs_root=str(root))
            result = service.get_log_tail("application", lines=2)

            self.assertTrue(result["success"])
            self.assertEqual(result["lines"], ["three", "four"])
            self.assertTrue(result["exists"])

    def test_missing_log_returns_empty_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = SystemLogsService(logs_root=tmpdir)
            result = service.get_log_tail("errors", lines=5)

            self.assertTrue(result["success"])
            self.assertEqual(result["lines"], [])
            self.assertFalse(result["exists"])


if __name__ == "__main__":
    unittest.main()
