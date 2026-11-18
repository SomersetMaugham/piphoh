import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from todo import cli
from todo.cli import main
from todo.commands import format_task


class CommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-cmd-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = str(self.tmp / "t.json")
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("TODO_FILE", None)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(["--file", self.f, *args])
        return rc, out.getvalue(), err.getvalue()

    def test_registry_contains_commands(self):
        self.assertIn("todo.commands", cli.COMMAND_MODULES)

    def test_format_task(self):
        self.assertEqual(format_task({"id": 3, "title": "T", "done": False}), "3 [ ] T")
        self.assertEqual(format_task({"id": 3, "title": "T", "done": True}), "3 [x] T")

    def test_full_cycle(self):
        self.assertEqual(self.run_main("add", " A ")[:2], (0, "Added task 1: A\n"))
        self.assertEqual(self.run_main("list")[1], "1 [ ] A\n")
        self.assertEqual(self.run_main("done", "1")[1], "Completed task 1: A\n")
        self.assertEqual(json.loads(self.run_main("list", "--json")[1])[0]["done"], True)
        self.assertEqual(self.run_main("rm", "1")[1], "Deleted task 1: A\n")
        self.assertEqual(self.run_main("list")[1], "No tasks.\n")

    def test_todo_error_returns_one(self):
        rc, out, err = self.run_main("rm", "7")
        self.assertEqual((rc, out, err), (1, "", "error: task 7 not found\n"))

    def test_bad_id_exits_two(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            main(["--file", self.f, "done", "x"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
