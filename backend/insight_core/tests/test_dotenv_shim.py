"""Discovery behaviour of dotenv, against either the vendored shim or real python-dotenv.

These originally patched pathlib.Path.cwd, which only steers the vendored shim under
backend/. The Docker image deletes that shim and installs real python-dotenv, which
resolves the file through os.getcwd()/frame inspection, so the patch was a no-op there
and the suite failed inside the container. Changing the process working directory works
for both implementations.
"""
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


@contextmanager
def working_directory(path: Path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _find(**kwargs):
    """find_dotenv(usecwd=True) on real python-dotenv; the shim takes no kwargs."""
    try:
        return find_dotenv(**kwargs)
    except TypeError:
        return find_dotenv()


class DotenvShimTests(unittest.TestCase):
    def test_load_dotenv_returns_false_when_no_env_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with working_directory(Path(temp_dir)):
                self.assertEqual(_find(usecwd=True), "")
                self.assertFalse(load_dotenv())

    def test_load_dotenv_reads_file_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("TEST_ENV_KEY=123\n", encoding="utf-8")

            old_value = os.environ.get("TEST_ENV_KEY")
            try:
                with working_directory(Path(temp_dir)):
                    found = _find(usecwd=True)
                    self.assertTrue(found, "dotenv should discover .env in the cwd")
                    self.assertTrue(load_dotenv(dotenv_path=found))
                    self.assertEqual(os.environ.get("TEST_ENV_KEY"), "123")
            finally:
                if old_value is None:
                    os.environ.pop("TEST_ENV_KEY", None)
                else:
                    os.environ["TEST_ENV_KEY"] = old_value


if __name__ == "__main__":
    unittest.main()
