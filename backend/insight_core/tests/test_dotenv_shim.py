import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.dotenv import find_dotenv, load_dotenv


class DotenvShimTests(unittest.TestCase):
    def test_load_dotenv_returns_false_when_no_env_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("pathlib.Path.cwd", return_value=Path(temp_dir)):
                self.assertEqual(find_dotenv(), "")
                self.assertFalse(load_dotenv())

    def test_load_dotenv_reads_file_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("TEST_ENV_KEY=123\n", encoding="utf-8")

            with patch("pathlib.Path.cwd", return_value=Path(temp_dir)):
                old_value = os.environ.get("TEST_ENV_KEY")
                try:
                    self.assertTrue(load_dotenv())
                    self.assertEqual(os.environ.get("TEST_ENV_KEY"), "123")
                finally:
                    if old_value is None:
                        os.environ.pop("TEST_ENV_KEY", None)
                    else:
                        os.environ["TEST_ENV_KEY"] = old_value


if __name__ == "__main__":
    unittest.main()
