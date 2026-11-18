"""S2 acceptance tests: CLI add/list/done/rm (contract .harness/contracts/s2.md).

Each test name carries the Acceptance item number (test_aN_...).
Every run uses a temp store file (via --file or TODO_FILE); HOME is pointed at a
temp dir and TODO_FILE is stripped from the inherited env so ~/.todo.json is
never touched.
"""
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

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class CliTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-s2-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.f = self.tmp / "t.json"
        env = {k: v for k, v in os.environ.items() if k != "TODO_FILE"}
        env["HOME"] = str(self.home)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env = env

    def run_raw(self, *args, env_extra=None):
        env = dict(self.env)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-m", "todo", *args],
            cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=60,
        )

    def run_cli(self, *args):
        return self.run_raw("--file", str(self.f), *args)

    def ok(self, *args):
        r = self.run_cli(*args)
        self.assertEqual(r.returncode, 0, f"args={args} stdout={r.stdout!r} stderr={r.stderr!r}")
        return r

    def list_json(self):
        r = self.ok("list", "--json")
        return json.loads(r.stdout)

    def lines(self, r):
        return r.stdout.splitlines()

    def assertNoTraceback(self, r):
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("Traceback", r.stdout)


class TestS2Cli(CliTestBase):
    def test_a1_add_then_list(self):
        r = self.ok("add", "Buy milk")
        self.assertEqual(r.stdout.strip(), "Added task 1: Buy milk")
        r = self.ok("list")
        self.assertTrue(self.lines(r)[0].startswith("1 [ ] Buy milk"), r.stdout)

    def test_a2_list_empty_nonexistent_file(self):
        r = self.ok("list")
        self.assertEqual(r.stdout.strip(), "No tasks.")
        self.assertEqual(self.list_json(), [])

    def test_a3_list_json_shape(self):
        self.ok("add", "A")
        self.ok("add", "B")
        data = self.list_json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertTrue(all(isinstance(t, dict) for t in data))
        self.assertEqual([t["id"] for t in data], [1, 2])
        self.assertEqual([t["title"] for t in data], ["A", "B"])
        self.assertEqual([t["done"] for t in data], [False, False])
        for t in data:
            self.assertIn("created", t)

    def test_a4_done_marks_complete(self):
        self.ok("add", "A")
        self.ok("add", "B")
        r = self.ok("done", "1")
        self.assertEqual(r.stdout.strip(), "Completed task 1: A")
        lines = self.lines(self.ok("list"))
        self.assertTrue(lines[0].startswith("1 [x] A"), lines)
        self.assertTrue(lines[1].startswith("2 [ ] B"), lines)

    def test_a5_rm_deletes(self):
        self.ok("add", "A")
        self.ok("add", "B")
        r = self.ok("rm", "2")
        self.assertEqual(r.stdout.strip(), "Deleted task 2: B")
        self.assertEqual([t["id"] for t in self.list_json()], [1])

    def test_a6_unknown_id_errors(self):
        self.ok("add", "A")
        for cmd in ("done", "rm"):
            with self.subTest(cmd=cmd):
                r = self.run_cli(cmd, "42")
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn("task 42 not found", r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertNoTraceback(r)

    def test_a7_non_integer_id_is_usage_error(self):
        r = self.run_cli("done", "abc")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("invalid", r.stderr)
        self.assertNoTraceback(r)

    def test_a7_add_without_title_is_usage_error(self):
        r = self.run_cli("add")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNoTraceback(r)

    def test_a8_blank_title_rejected(self):
        for title in ("", "   "):
            with self.subTest(title=title):
                r = self.run_cli("add", title)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertTrue(r.stderr.startswith("error:"), repr(r.stderr))
                self.assertNoTraceback(r)
        self.assertEqual(self.list_json(), [])

    def test_a9_env_todo_file_fallback(self):
        envf = self.tmp / "env.json"
        r = self.run_raw("add", "X", env_extra={"TODO_FILE": str(envf)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(envf.is_file())
        self.assertFalse((self.home / ".todo.json").exists())
        from todo.store import TaskStore
        tasks = TaskStore(envf).list()
        self.assertEqual([t["title"] for t in tasks], ["X"])

    def test_a9_file_option_beats_env(self):
        envf = self.tmp / "env.json"
        r = self.run_raw("--file", str(self.f), "add", "Y", env_extra={"TODO_FILE": str(envf)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.f.is_file())
        self.assertFalse(envf.exists())

    def test_a10_invalid_json_file(self):
        self.f.write_text("{not json", encoding="utf-8")
        r = self.run_cli("list")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(r.stderr.startswith("error:"), repr(r.stderr))
        self.assertNoTraceback(r)

    def test_a11_in_process_main(self):
        from todo.cli import main
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                contextlib.redirect_stdout(buf):
            os.environ.pop("TODO_FILE", None)
            rc = main(["--file", str(self.f), "add", "Z"])
        self.assertEqual(rc, 0)
        self.assertIn("Added task 1: Z", buf.getvalue())

    def test_a12_cli_writes_visible_to_library(self):
        self.ok("add", "X")
        from todo.store import TaskStore
        self.assertEqual(TaskStore(self.f).get(1)["title"], "X")


if __name__ == "__main__":
    unittest.main()
