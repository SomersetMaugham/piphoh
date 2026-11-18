import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

import todo
from todo.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]


class SmokeTest(unittest.TestCase):
    def test_version_is_non_empty_str(self):
        self.assertIsInstance(todo.__version__, str)
        self.assertTrue(todo.__version__)

    def test_main_version_exits_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"todo {todo.__version__}")

    def test_main_no_command_exits_two(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            main([])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("usage", err.getvalue())

    def test_module_entry_point(self):
        r = subprocess.run([sys.executable, "-m", "todo", "--version"],
                           cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), f"todo {todo.__version__}")
        r = subprocess.run([sys.executable, "-m", "todo"],
                           cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertIn("usage", r.stderr)


if __name__ == "__main__":
    unittest.main()
