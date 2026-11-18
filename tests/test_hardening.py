"""Dev-owned tests for S7 error hardening (port, malformed store, ~ paths, --file anywhere)."""

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from todo import StoreError, TaskStore, cli
from todo.server import _port

ROOT = Path(__file__).resolve().parent.parent
GOOD = {"id": 1, "title": "x", "done": False, "created": "2026-01-01T00:00:00Z"}


def run_cli(*args, env_extra=None, cwd=ROOT):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("TODO_FILE", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "todo", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=30)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.store = self.tmp / "s.json"

    def tearDown(self):
        self._tmp.cleanup()

    def write_store(self, tasks, next_id=2):
        self.store.write_text(json.dumps({"version": 1, "next_id": next_id, "tasks": tasks}))


class TestPort(unittest.TestCase):
    def test_port_type(self):
        self.assertEqual((_port("0"), _port("65535"), _port("8000")), (0, 65535, 8000))
        for bad in ("65536", "-1", "abc", "", "1.5"):
            with self.assertRaises(argparse.ArgumentTypeError) as cm:
                _port(bad)
            self.assertEqual(str(cm.exception),
                             f"port must be an integer from 0 to 65535, got {bad!r}")

    def test_cli_bad_port(self):
        r = run_cli("serve", "--port", "99999")
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.rstrip("\n").endswith(
            "todo serve: error: argument --port: port must be an integer from 0 to 65535, "
            "got '99999'"))
        self.assertNotIn("Traceback", r.stderr)


class TestMalformedStore(Base):
    CASES = [
        ([{k: v for k, v in GOOD.items() if k != "created"}], "task 1 has invalid 'created'"),
        ([dict(GOOD, created=5)], "task 1 has invalid 'created'"),
        ([dict(GOOD, created="yesterday")], "task 1 has invalid 'created'"),
        ([dict(GOOD, due=5)], "task 1 has invalid 'due'"),
        ([dict(GOOD, due="2026-02-30")], "task 1 has invalid 'due'"),
        ([dict(GOOD, priority="urgent")], "task 1 has invalid 'priority'"),
        ([dict(GOOD, priority=None)], "task 1 has invalid 'priority'"),
        ([GOOD, dict(GOOD, title="y")], "duplicate task id 1"),
    ]

    def test_load_rejects(self):
        for tasks, why in self.CASES:
            with self.subTest(why=why, tasks=tasks):
                self.write_store(tasks)
                with self.assertRaises(StoreError) as cm:
                    TaskStore(self.store).list()
                self.assertEqual(str(cm.exception), f"invalid store file {self.store}: {why}")

    def test_legal_variants(self):
        self.write_store([GOOD, dict(GOOD, id=2, due=None, priority="high"),
                          dict(GOOD, id=3, due="2026-12-01")], next_id=4)
        tasks = TaskStore(self.store).list()
        self.assertEqual([(t["due"], t["priority"]) for t in tasks],
                         [(None, "normal"), (None, "high"), ("2026-12-01", "normal")])

    def test_cli_export_no_output_file(self):
        self.write_store([{k: v for k, v in GOOD.items() if k != "created"}])
        before = self.store.read_bytes()
        out = self.tmp / "o.csv"
        r = run_cli("--file", str(self.store), "export", str(out))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr, f"error: invalid store file {self.store}: task 1 has invalid 'created'\n")
        self.assertFalse(out.exists())
        self.assertEqual(self.store.read_bytes(), before)


class TestLastResort(unittest.TestCase):
    def test_unexpected_exception(self):
        err = io.StringIO()
        with mock.patch.object(TaskStore, "list", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["list"]), 1)
        self.assertEqual(err.getvalue(), "error: unexpected RuntimeError: boom\n")

    def test_keyboard_interrupt(self):
        err, out = io.StringIO(), io.StringIO()
        with mock.patch.object(TaskStore, "list", side_effect=KeyboardInterrupt), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["list"]), 130)
        self.assertEqual((err.getvalue(), out.getvalue()), ("", ""))


class TestTildeAndFile(Base):
    def test_tilde_paths(self):
        home = self.tmp / "home"
        home.mkdir()
        cwd = self.tmp / "cwd"
        cwd.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            self.assertEqual(TaskStore("~/a.json").path, home / "a.json")
        env = {"HOME": str(home), "PYTHONPATH": str(ROOT)}
        r = run_cli("add", "A", env_extra=dict(env, TODO_FILE="~/b.json"), cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_cli("--file", "~/c.json", "add", "C", env_extra=env, cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_cli("add", "D", "--file", "~/d.json", env_extra=env, cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in ("b.json", "c.json", "d.json"):
            self.assertTrue((home / name).exists(), name)
        self.assertFalse((cwd / "~").exists())

    def test_file_after_subcommand_parsing(self):
        p = cli.build_parser()
        for argv in (["serve"], ["list"], ["add", "T"], ["done", "1"], ["rm", "1"],
                     ["export", "o.csv"], ["import", "o.csv"]):
            self.assertEqual(p.parse_args(argv + ["--file", "X"]).file, "X", argv)
        self.assertEqual(p.parse_args(["--file", "A", "list", "--file", "B"]).file, "B")
        self.assertEqual(p.parse_args(["--file", "A", "list"]).file, "A")
        self.assertIsNone(p.parse_args(["list"]).file)

    def test_file_after_subcommand_cli(self):
        r = run_cli("add", "T", "--file", str(self.store))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_cli("list", "--json", "--file", str(self.store))
        self.assertEqual([t["title"] for t in json.loads(r.stdout)], ["T"])


if __name__ == "__main__":
    unittest.main()
