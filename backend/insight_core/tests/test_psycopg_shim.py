import subprocess
import unittest
from unittest.mock import patch

from psycopg import _run_psql


class PsycopgShimTests(unittest.TestCase):
    def test_run_psql_uses_dash_c_for_small_queries(self):
        captured = {}

        def fake_run(command, check, capture_output, text):
            captured["command"] = command
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        with patch("psycopg.subprocess.run", side_effect=fake_run):
            output = _run_psql("postgresql:///test", "SELECT 1;", expect_output=True)

        self.assertEqual(output, "ok")
        self.assertIn("-c", captured["command"])
        self.assertNotIn("-f", captured["command"])

    def test_run_psql_uses_temp_file_for_large_queries(self):
        captured = {}
        sql_text = "SELECT '" + ("x" * 13000) + "';"

        def fake_run(command, check, capture_output, text):
            captured["command"] = command
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        with patch("psycopg.subprocess.run", side_effect=fake_run):
            output = _run_psql("postgresql:///test", sql_text, expect_output=True)

        self.assertEqual(output, "ok")
        self.assertIn("-f", captured["command"])
        self.assertNotIn("-c", captured["command"])
        file_index = captured["command"].index("-f") + 1
        sql_path = captured["command"][file_index]
        self.assertTrue(sql_path.endswith(".sql"))


if __name__ == "__main__":
    unittest.main()
