"""S7 acceptance tests: error hardening (contract .harness/contracts/S7.md).

Each test name carries the Acceptance item number (test_aN_...).
CLI runs use `python -B -m todo` as a subprocess with cwd = a temp work dir and
PYTHONPATH = repo root. HOME points at a temp dir and TODO_FILE is stripped so
~/.todo.json is never touched; `~` expansion is checked against that temp HOME.
"""
import argparse
import contextlib
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

C1 = "2026-01-02T03:04:05Z"
PORT_MSG = "error: argument --port: port must be an integer from 0 to 65535"


def parse(argv):
    """build_parser().parse_args, turning argparse's SystemExit into a test failure."""
    from todo.cli import build_parser
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return build_parser().parse_args(argv)
    except SystemExit as exc:
        raise AssertionError(f"parse_args({argv}) exited {exc.code}: {err.getvalue().strip()}")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-s7-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.x = self.tmp / "x.json"
        env = {k: v for k, v in os.environ.items() if k not in ("TODO_FILE", "PYTHONPATH")}
        env["HOME"] = str(self.home)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT)
        self.env = env
        from todo import TaskStore
        self.TaskStore = TaskStore

    def run_raw(self, *args, cwd=None, env_extra=None):
        env = dict(self.env)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-B", "-m", "todo", *args],
            cwd=str(cwd or self.work), capture_output=True, text=True, env=env, timeout=60,
        )

    def ok(self, *args, **kw):
        r = self.run_raw(*args, **kw)
        self.assertEqual(r.returncode, 0, f"args={args} stdout={r.stdout!r} stderr={r.stderr!r}")
        return r

    def assertNoTraceback(self, r):
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("Traceback", r.stdout)

    def write_store(self, path, tasks, next_id=2):
        data = {"version": 1, "next_id": next_id, "tasks": tasks}
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return Path(path).read_bytes()

    def assertNoTildeDir(self):
        self.assertFalse((self.work / "~").exists(), "a literal '~' dir was created in cwd")


# -- 1 ---------------------------------------------------------------------
class TestA1ServePort(Base):
    def test_a1_out_of_range_ports_usage_error(self):
        for value in ("99999", "-1", "65536"):
            with self.subTest(port=value):
                r = self.run_raw("--file", str(self.x), "serve", "--port", value)
                self.assertEqual(r.returncode, 2, f"stdout={r.stdout!r} stderr={r.stderr!r}")
                self.assertNoTraceback(r)
                self.assertIn(PORT_MSG, r.stderr)
                self.assertTrue(
                    r.stderr.rstrip("\n").endswith(
                        f"todo serve: {PORT_MSG}, got '{value}'"), r.stderr)
                self.assertEqual(r.stdout, "")

    def test_a1_non_integer_port_usage_error(self):
        r = self.run_raw("--file", str(self.x), "serve", "--port", "abc")
        self.assertEqual(r.returncode, 2, f"stdout={r.stdout!r} stderr={r.stderr!r}")
        self.assertNoTraceback(r)
        # Interface: anything not an integer 0..65535 gets the same message.
        self.assertTrue(
            r.stderr.rstrip("\n").endswith(f"todo serve: {PORT_MSG}, got 'abc'"), r.stderr)

    def test_a1_boundary_ports_accepted_by_parser(self):
        for value, expected in (("0", 0), ("65535", 65535), ("8000", 8000)):
            with self.subTest(port=value):
                self.assertEqual(parse(["serve", "--port", value]).port, expected)

    def test_a1_serve_catches_overflow_from_make_server(self):
        # Interface: `_serve` maps OverflowError/ValueError from make_server to an error line.
        from todo import server
        args = argparse.Namespace(file=str(self.x), host="127.0.0.1", port=99999)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                rc = server._serve(args)
            except (OverflowError, ValueError) as exc:
                self.fail(f"_serve let {type(exc).__name__} escape: {exc}")
        self.assertEqual(rc, 1)
        self.assertTrue(err.getvalue().startswith("error: cannot listen on 127.0.0.1:99999: "),
                        err.getvalue())


# -- 2 ---------------------------------------------------------------------
GOOD = {"id": 1, "title": "x", "done": False, "created": C1}
MALFORMED = [
    ("missing created", [{"id": 1, "title": "x", "done": False}], "task 1 has invalid 'created'"),
    ("bad created", [dict(GOOD, created="yesterday")], "task 1 has invalid 'created'"),
    ("created not str", [dict(GOOD, created=5)], "task 1 has invalid 'created'"),
    ("due 5", [dict(GOOD, due=5)], "task 1 has invalid 'due'"),
    ("due bad date", [dict(GOOD, due="2026-02-30")], "task 1 has invalid 'due'"),
    ("priority urgent", [dict(GOOD, priority="urgent")], "task 1 has invalid 'priority'"),
    ("duplicate id", [GOOD, dict(GOOD, title="y")], "duplicate task id 1"),
]
COMMANDS = [("list",), ("list", "--json"), ("add", "Z"), ("done", "1"), ("export", "o.csv")]


class TestA2MalformedStore(Base):
    def test_a2_malformed_records_rejected_by_every_command(self):
        for name, tasks, why in MALFORMED:
            for cmd in COMMANDS:
                with self.subTest(case=name, cmd=cmd):
                    before = self.write_store(self.x, tasks)  # fresh per subtest
                    (self.work / "o.csv").unlink(missing_ok=True)
                    r = self.run_raw("--file", str(self.x), *cmd)
                    self.assertEqual(r.returncode, 1, f"stdout={r.stdout!r} stderr={r.stderr!r}")
                    self.assertNoTraceback(r)
                    self.assertEqual(r.stderr, f"error: invalid store file {self.x}: {why}\n")
                    self.assertEqual(r.stdout, "")
                    self.assertEqual(self.x.read_bytes(), before, "store file changed")
                    self.assertFalse((self.work / "o.csv").exists(), "o.csv was created")

    def test_a2_library_load_raises_store_error(self):
        from todo.errors import StoreError
        for name, tasks, why in MALFORMED:
            with self.subTest(case=name):
                self.write_store(self.x, tasks)
                with self.assertRaises(StoreError) as cm:
                    self.TaskStore(self.x).list()
                self.assertEqual(str(cm.exception), f"invalid store file {self.x}: {why}")


# -- 3 ---------------------------------------------------------------------
class TestA3RestMalformedStore(Base):
    def _get(self, port, path="/tasks"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, resp.getheader("Content-Type", ""), resp.read()
        finally:
            conn.close()

    def test_a3_get_tasks_500_json_server_survives(self):
        from todo.server import make_server
        self.write_store(self.x, [{"id": 1, "title": "x", "done": False}])
        srv = make_server(self.TaskStore(self.x), "127.0.0.1", port=0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()

        def stop():
            srv.shutdown()
            srv.server_close()
            t.join(timeout=5)
        self.addCleanup(stop)

        for _ in range(2):
            status, ctype, body = self._get(port)
            self.assertEqual(status, 500, body)
            self.assertTrue(ctype.startswith("application/json"), ctype)
            obj = json.loads(body)
            self.assertIsInstance(obj, dict)
            self.assertIsInstance(obj.get("error"), str)
        self.assertTrue(t.is_alive(), "server thread died")
        # Server still serves once the file is fixed.
        self.write_store(self.x, [GOOD])
        status, _, body = self._get(port)
        self.assertEqual(status, 200, body)
        self.assertEqual([x["id"] for x in json.loads(body)], [1])


# -- 4 ---------------------------------------------------------------------
class TestA4LegacyBackfill(Base):
    def test_a4_legacy_task_lists_fine(self):
        before = self.write_store(self.x, [GOOD])  # no due/priority keys
        r = self.ok("--file", str(self.x), "list")
        self.assertEqual(r.stdout.splitlines(), ["1 [ ] x"])
        r = self.ok("--file", str(self.x), "list", "--json")
        (task,) = json.loads(r.stdout)
        self.assertEqual((task["due"], task["priority"]), (None, "normal"))
        self.assertEqual(self.x.read_bytes(), before)

    def test_a4_explicit_null_due_and_valid_values_legal(self):
        self.write_store(self.x, [dict(GOOD, due=None, priority="high"),
                                  dict(GOOD, id=2, due="2026-12-01", priority="low")], next_id=3)
        r = self.ok("--file", str(self.x), "list")
        self.assertEqual(r.stdout.splitlines(),
                         ["1 [ ] x (priority high)", "2 [ ] x (due 2026-12-01, priority low)"])


# -- 5 ---------------------------------------------------------------------
class TestA5LastResortHandler(Base):
    def _main(self, side_effect):
        from todo import cli
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(self.TaskStore, "list", side_effect=side_effect), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cli.main(["--file", str(self.x), "list"])
            except BaseException as exc:  # noqa: BLE001 - report as failure, not error
                rc = exc
        return rc, out.getvalue(), err.getvalue()

    def test_a5_unexpected_exception(self):
        rc, out, err = self._main(RuntimeError("boom"))
        if isinstance(rc, BaseException):
            self.fail(f"cli.main let {type(rc).__name__} escape: {rc}")
        self.assertEqual(rc, 1)
        self.assertEqual(err, "error: unexpected RuntimeError: boom\n")
        self.assertEqual(out, "")

    def test_a5_keyboard_interrupt_130(self):
        rc, out, err = self._main(KeyboardInterrupt())
        if isinstance(rc, BaseException):
            self.fail(f"cli.main let {type(rc).__name__} escape")
        self.assertEqual(rc, 130)
        self.assertEqual((out, err), ("", ""))

    def test_a5_todo_error_unchanged(self):
        from todo.errors import StoreError
        rc, out, err = self._main(StoreError("disk on fire"))
        self.assertEqual(rc, 1)
        self.assertEqual(err, "error: disk on fire\n")


# -- 6 ---------------------------------------------------------------------
class TestA6TildePaths(Base):
    def test_a6_library_explicit_path_expands(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertEqual(self.TaskStore("~/a.json").path, self.home / "a.json")

    def test_a6_library_env_path_expands(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home), "TODO_FILE": "~/e.json"}):
            self.assertEqual(self.TaskStore().path, self.home / "e.json")

    def test_a6_todo_file_env_tilde(self):
        r = self.ok("add", "A", env_extra={"TODO_FILE": "~/b.json"})
        self.assertEqual(r.stdout.strip(), "Added task 1: A")
        target = self.home / "b.json"
        self.assertTrue(target.exists(), "store not written under $HOME")
        self.assertEqual([t["title"] for t in self.TaskStore(target).list()], ["A"])
        self.assertNoTildeDir()

    def test_a6_file_option_tilde(self):
        self.ok("--file", "~/c.json", "add", "C")
        target = self.home / "c.json"
        self.assertTrue(target.exists(), "store not written under $HOME")
        self.assertEqual([t["title"] for t in self.TaskStore(target).list()], ["C"])
        self.assertNoTildeDir()


# -- 7 ---------------------------------------------------------------------
class TestA7FileAfterSubcommand(Base):
    SEQ = [("add", "T"), ("list",), ("done", "1"), ("list", "--json"),
           ("export", "o.csv"), ("rm", "1"), ("import", "o.csv"), ("list",)]

    def _run_seq(self, store, after):
        cwd = self.tmp / ("after" if after else "before")
        cwd.mkdir()
        outs = []
        for cmd in self.SEQ:
            args = (*cmd, "--file", str(store)) if after else ("--file", str(store), *cmd)
            r = self.ok(*args, cwd=cwd)
            outs.append(r.stdout)
        return outs, (cwd / "o.csv").read_text(encoding="utf-8")

    @staticmethod
    def _strip_created(tasks):
        return [{k: v for k, v in t.items() if k != "created"} for t in tasks]

    def test_a7_every_command_accepts_trailing_file(self):
        before_store, after_store = self.tmp / "b4.json", self.tmp / "af.json"
        outs_b, csv_b = self._run_seq(before_store, after=False)
        outs_a, csv_a = self._run_seq(after_store, after=True)
        # list --json and the CSV carry `created`; compare those without it.
        jb, ja = json.loads(outs_b[3]), json.loads(outs_a[3])
        self.assertEqual(self._strip_created(ja), self._strip_created(jb))
        outs_b[3] = outs_a[3] = None
        self.assertEqual(outs_a, outs_b)
        self.assertEqual([l.split(",")[:3] for l in csv_a.splitlines()],
                         [l.split(",")[:3] for l in csv_b.splitlines()])
        self.assertEqual(self._strip_created(self.TaskStore(after_store).list()),
                         self._strip_created(self.TaskStore(before_store).list()))
        self.assertTrue(after_store.exists())
        self.assertFalse((self.home / ".todo.json").exists(), "default store was used")

    def test_a7_serve_parser_has_file(self):
        self.assertEqual(parse(["serve", "--file", "X"]).file, "X")

    def test_a7_trailing_file_wins(self):
        a, b = self.tmp / "A.json", self.tmp / "B.json"
        self.TaskStore(b).add("in B")
        self.ok("--file", str(a), "add", "new", "--file", str(b))
        self.assertFalse(a.exists(), "leading --file was used")
        r = self.ok("--file", str(a), "list", "--file", str(b))
        self.assertEqual(r.stdout.splitlines(), ["1 [ ] in B", "2 [ ] new"])
        self.assertFalse(a.exists())
        self.assertEqual(parse(["--file", "A", "list", "--file", "B"]).file, "B")
        self.assertEqual(parse(["--file", "A", "list"]).file, "A")

    def test_a7_no_file_is_none(self):
        for argv in (["list"], ["serve"], ["add", "T"]):
            with self.subTest(argv=argv):
                self.assertIsNone(parse(argv).file)


if __name__ == "__main__":
    unittest.main()
