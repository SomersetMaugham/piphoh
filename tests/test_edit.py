import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from todo.cli import main

ROOT = Path(__file__).resolve().parent.parent


class EditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-edit-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = str(self.tmp / "t.json")
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("TODO_FILE", None)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = main(["--file", self.f, *args])
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    def task(self, task_id=1):
        rc, out, _ = self.run_main("list", "--json")
        return next(t for t in json.loads(out) if t["id"] == task_id)

    def raw(self):
        return Path(self.f).read_bytes()

    def test_edit_all_fields(self):
        self.run_main("add", "Buy milk")
        self.run_main("add", "Other")
        before = self.task()
        other = self.task(2)
        rc, out, err = self.run_main("edit", "1", "--title", "Buy oat milk",
                                     "--due", "2026-12-01", "--priority", "high")
        self.assertEqual((rc, out, err), (0, "Updated task 1: Buy oat milk\n", ""))
        t = self.task()
        self.assertEqual((t["title"], t["due"], t["priority"], t["done"], t["created"]),
                         ("Buy oat milk", "2026-12-01", "high", False, before["created"]))
        self.assertEqual(self.task(2), other)
        rc, out, _ = self.run_main("list")
        self.assertEqual(out.splitlines()[0], "1 [ ] Buy oat milk (due 2026-12-01, priority high)")

    def test_partial_edits(self):
        self.run_main("add", "A", "--due", "2026-12-01", "--priority", "high")
        self.assertEqual(self.run_main("edit", "1", "--no-due")[0], 0)
        t = self.task()
        self.assertEqual((t["due"], t["priority"]), (None, "high"))
        self.assertEqual(self.run_main("list")[1], "1 [ ] A (priority high)\n")
        self.run_main("edit", "1", "--priority", "low")
        t = self.task()
        self.assertEqual((t["title"], t["due"], t["priority"]), ("A", None, "low"))
        rc, out, _ = self.run_main("edit", "1", "--title", "  Trimmed  ")
        self.assertEqual((rc, out), (0, "Updated task 1: Trimmed\n"))

    def test_nothing_to_change(self):
        self.run_main("add", "A")
        before = self.raw()
        rc, out, err = self.run_main("edit", "1")
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(err, "error: nothing to change (use --title, --due, --no-due or --priority)\n")
        self.assertEqual(self.raw(), before)

    def test_validation_errors_leave_store(self):
        self.run_main("add", "A")
        before = self.raw()
        for args in (["--due", "2026-02-30"], ["--due", "tomorrow"], ["--title", "  "]):
            rc, out, err = self.run_main("edit", "1", *args)
            self.assertEqual((rc, out), (1, ""), args)
            self.assertTrue(err.startswith("error:"), err)
            self.assertEqual(self.raw(), before)
        err = self.run_main("edit", "1", "--due", "2026-02-30")[2]
        self.assertEqual(err, "error: due is not a valid calendar date: '2026-02-30'\n")

    def test_not_found(self):
        self.run_main("add", "A")
        self.assertEqual(self.run_main("edit", "42", "--title", "x"),
                         (1, "", "error: task 42 not found\n"))

    def test_usage_errors_exit_2(self):
        self.run_main("add", "A")
        for args in (["1", "--due", "2026-12-01", "--no-due"], ["1", "--priority", "urgent"],
                     ["abc", "--title", "x"]):
            proc = subprocess.run(
                [sys.executable, "-B", "-m", "todo", "--file", self.f, "edit", *args],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2, args)
            self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
