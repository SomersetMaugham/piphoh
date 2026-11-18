"""S3 acceptance tests: due date + priority, filter/sort (contract .harness/contracts/s3.md).

Each test name carries the Acceptance item number (test_aN_...).
All stores use temp files; HOME points at a temp dir and TODO_FILE is removed,
so ~/.todo.json is never touched. Tasks are checked by key subset.
Item 11 needs S4's todo.server; it is SKIPPED (not passed) while that module
is absent, and QA verification must report such a skip.
"""
import http.client
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


class S3Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-s3-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = {k: v for k, v in os.environ.items() if k != "TODO_FILE"}
        env["HOME"] = str(self.home)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env = env
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        from todo.store import TaskStore
        from todo.errors import ValidationError, TodoError
        self.TaskStore = TaskStore
        self.ValidationError = ValidationError
        self.TodoError = TodoError
        self.p = self.tmp / "t.json"

    def store(self, path=None):
        return self.TaskStore(self.p if path is None else path)

    def ids(self, tasks):
        return [t["id"] for t in tasks]

    def cli(self, *args, path=None):
        return subprocess.run(
            [sys.executable, "-m", "todo", "--file", str(self.p if path is None else path), *args],
            cwd=str(REPO_ROOT), capture_output=True, text=True, env=self.env, timeout=60,
        )

    def cli_ok(self, *args):
        r = self.cli(*args)
        self.assertEqual(r.returncode, 0, f"args={args} stdout={r.stdout!r} stderr={r.stderr!r}")
        return r

    def assertNoTraceback(self, r):
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("Traceback", r.stdout)

    def fixture_sort(self):
        """Interface fixture: 1(due 12-05, low) 2(no due, high) 3(due 12-01, normal)."""
        s = self.store()
        s.add("A", due="2026-12-05", priority="low")
        s.add("B", priority="high")
        s.add("C", due="2026-12-01", priority="normal")
        return s

    def write_raw(self, tasks, next_id=None):
        data = {"version": 1, "next_id": next_id or (max(t["id"] for t in tasks) + 1), "tasks": tasks}
        self.p.write_text(json.dumps(data, indent=2), encoding="utf-8")


class TestS3Store(S3Base):
    def test_a1_add_due_priority_persists(self):
        t = self.store().add("Pay rent", due="2026-12-01", priority="high")
        self.assertEqual(t["due"], "2026-12-01")
        self.assertEqual(t["priority"], "high")
        self.assertTrue({"id", "title", "done", "created"} <= set(t))
        got = self.TaskStore(self.p).get(1)
        self.assertEqual(got["title"], "Pay rent")
        self.assertEqual(got["due"], "2026-12-01")
        self.assertEqual(got["priority"], "high")

    def test_a1_cli_list_line_with_suffix(self):
        self.store().add("Pay rent", due="2026-12-01", priority="high")
        r = self.cli_ok("list")
        self.assertEqual(r.stdout.splitlines()[0], "1 [ ] Pay rent (due 2026-12-01, priority high)")

    def test_a2_defaults(self):
        s = self.store()
        for kwargs in ({}, {"due": None, "priority": None}):
            with self.subTest(kwargs=kwargs):
                t = s.add("x", **kwargs)
                self.assertIn("due", t)
                self.assertIsNone(t["due"])
                self.assertEqual(t["priority"], "normal")
                got = self.store().get(t["id"])
                self.assertIsNone(got["due"])
                self.assertEqual(got["priority"], "normal")

    def test_a3_invalid_due_and_priority_rejected(self):
        s = self.store()
        s.add("keep")
        before = self.p.read_bytes()
        cases = [{"due": v} for v in ("2026-02-30", "2026-1-5", "tomorrow", 20261201)]
        cases += [{"priority": v} for v in ("HIGH", "urgent", 1)]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(self.ValidationError) as cm:
                    s.add("x", **kwargs)
                self.assertIsInstance(cm.exception, self.TodoError)
        self.assertEqual(self.ids(self.store().list()), [1])
        self.assertEqual(self.p.read_bytes(), before)

    def test_a4_update_due_priority_persist(self):
        s = self.store()
        s.add("t")
        r = s.update(1, due="2027-01-01")
        self.assertEqual(r["due"], "2027-01-01")
        self.assertEqual(self.store().get(1)["due"], "2027-01-01")
        r = s.update(1, priority="low")
        self.assertEqual(r["priority"], "low")
        got = self.store().get(1)
        self.assertEqual(got["priority"], "low")
        self.assertEqual(got["due"], "2027-01-01")
        r = s.update(1, due=None)
        self.assertIsNone(r["due"])
        got = self.store().get(1)
        self.assertIsNone(got["due"])
        self.assertEqual(got["priority"], "low")

    def test_a4_update_invalid_and_validation_before_lookup(self):
        s = self.store()
        s.add("t", priority="high")
        with self.assertRaises(self.ValidationError):
            s.update(1, priority=None)
        with self.assertRaises(self.ValidationError):
            s.update(99, priority="bad")  # not TaskNotFound
        self.assertEqual(self.store().get(1)["priority"], "high")

    def test_a4_update_fields_constants(self):
        self.assertEqual(tuple(self.TaskStore.CREATE_FIELDS), ("title", "due", "priority"))
        self.assertEqual(tuple(self.TaskStore.UPDATE_FIELDS), ("title", "done", "due", "priority"))

    def test_a5_pre_s3_file_backfilled_without_rewrite(self):
        self.write_raw([
            {"id": 1, "title": "old one", "done": False, "created": "2026-01-01T00:00:00Z"},
            {"id": 2, "title": "old two", "done": True, "created": "2026-01-02T00:00:00Z"},
        ])
        before = self.p.read_bytes()
        mtime = self.p.stat().st_mtime_ns
        tasks = self.store().list()
        self.assertEqual(self.ids(tasks), [1, 2])
        for t in tasks:
            self.assertIsNone(t["due"])
            self.assertEqual(t["priority"], "normal")
        self.assertEqual(self.store().get(2)["priority"], "normal")
        self.assertEqual(self.store().list(sort="due"), tasks)
        self.assertEqual(self.p.read_bytes(), before)
        self.assertEqual(self.p.stat().st_mtime_ns, mtime)

    def test_a6_status_filter_partitions(self):
        s = self.store()
        for title in "abcd":
            s.add(title)
        s.complete(2)
        s.complete(4)
        open_ids = self.ids(s.list(status="open"))
        done_ids = self.ids(s.list(status="done"))
        self.assertEqual(open_ids, [1, 3])
        self.assertEqual(done_ids, [2, 4])
        self.assertEqual(sorted(open_ids + done_ids), self.ids(s.list()))
        self.assertTrue(all(t["done"] is False for t in s.list(status="open")))
        self.assertTrue(all(t["done"] is True for t in s.list(status="done")))
        self.assertEqual(self.ids(s.list(status=None)), [1, 2, 3, 4])

    def test_a6_bad_status_or_sort_rejected(self):
        s = self.store()
        s.add("a")
        with self.assertRaises(self.ValidationError):
            s.list(status="all")
        with self.assertRaises(self.ValidationError):
            s.list(sort="title")

    def test_a7_sort_due_and_priority_fixture(self):
        s = self.fixture_sort()
        self.assertEqual(self.ids(s.list(sort="due")), [3, 1, 2])
        self.assertEqual(self.ids(s.list(sort="priority")), [2, 3, 1])
        self.assertEqual(self.ids(s.list(sort=None)), [1, 2, 3])
        self.assertEqual(self.ids(s.list()), [1, 2, 3])

    def test_a7_sort_tie_breaks_by_id(self):
        s = self.store()
        s.add("p", priority="high")
        s.add("q", due="2026-12-01")
        s.add("r", priority="high")
        s.add("t", due="2026-12-01")
        s.add("u")
        self.assertEqual(self.ids(s.list(sort="priority")), [1, 3, 2, 4, 5])
        self.assertEqual(self.ids(s.list(sort="due")), [2, 4, 1, 3, 5])

    def test_a7_sort_created_equal_timestamps_by_id(self):
        ts = "2026-03-01T10:00:00Z"
        self.write_raw([
            {"id": 3, "title": "c", "done": False, "created": ts},
            {"id": 1, "title": "a", "done": False, "created": ts},
            {"id": 2, "title": "b", "done": False, "created": ts},
        ])
        self.assertEqual(self.ids(self.store().list(sort="created")), [1, 2, 3])

    def test_a7_sort_created_ascending(self):
        self.write_raw([
            {"id": 1, "title": "late", "done": False, "created": "2026-03-02T00:00:00Z"},
            {"id": 2, "title": "early", "done": False, "created": "2026-03-01T00:00:00Z"},
            {"id": 3, "title": "mid", "done": False, "created": "2026-03-01T12:00:00Z"},
        ])
        self.assertEqual(self.ids(self.store().list(sort="created")), [2, 3, 1])

    def test_a7_status_and_sort_combine(self):
        s = self.fixture_sort()
        s.add("D", priority="high")  # id 4
        s.complete(2)
        self.assertEqual(self.ids(s.list(status="open", sort="priority")), [4, 3, 1])
        self.assertEqual(self.ids(s.list(status="done", sort="priority")), [2])


class TestS3Cli(S3Base):
    def test_a8_cli_add_with_flags(self):
        r = self.cli_ok("add", "X", "--due", "2026-12-01", "--priority", "low")
        self.assertEqual(r.stdout.strip(), "Added task 1: X")
        t = self.store().get(1)
        self.assertEqual(t["due"], "2026-12-01")
        self.assertEqual(t["priority"], "low")

    def test_a8_cli_bad_priority_exit_2(self):
        r = self.cli("add", "X", "--priority", "urgent")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNoTraceback(r)
        self.assertEqual(self.store().list(), [])

    def test_a8_cli_bad_due_exit_1(self):
        r = self.cli("add", "X", "--due", "2026-13-01")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(r.stderr.startswith("error:"), repr(r.stderr))
        self.assertNoTraceback(r)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.store().list(), [])

    def test_a9_cli_status_done_empty(self):
        self.cli_ok("add", "open one")
        r = self.cli_ok("list", "--status", "done")
        self.assertEqual(r.stdout.strip(), "No tasks.")

    def test_a9_cli_bad_sort_exit_2(self):
        r = self.cli("list", "--sort", "bogus")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNoTraceback(r)
        r = self.cli("list", "--status", "all")
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_a9_cli_status_sort_json(self):
        s = self.fixture_sort()
        s.add("D", due="2026-11-30")  # id 4
        s.complete(4)
        r = self.cli_ok("list", "--status", "open", "--sort", "due", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(self.ids(data), [3, 1, 2])
        for t in data:
            self.assertIn("due", t)
            self.assertIn("priority", t)
            self.assertIs(t["done"], False)
        self.assertIsNone(data[2]["due"])
        self.assertEqual(data[2]["priority"], "high")

    def test_a9_cli_sort_due_example_lines(self):
        self.fixture_sort()
        r = self.cli_ok("list", "--sort", "due")
        self.assertEqual(r.stdout.splitlines(), [
            "3 [ ] C (due 2026-12-01)",
            "1 [ ] A (due 2026-12-05, priority low)",
            "2 [ ] B (priority high)",
        ])

    def test_a10_default_task_line_has_no_suffix(self):
        self.cli_ok("add", "Plain")
        self.cli_ok("add", "Done one")
        self.cli_ok("done", "2")
        r = self.cli_ok("list")
        self.assertEqual(r.stdout, "1 [ ] Plain\n2 [x] Done one\n")
        # explicit default priority is still a default value -> no suffix
        self.store().add("Normal", priority="normal")
        r = self.cli_ok("list")
        self.assertEqual(r.stdout.splitlines()[2], "3 [ ] Normal")


class TestS3Rest(S3Base):
    def setUp(self):
        super().setUp()
        try:
            from todo.server import make_server
        except ModuleNotFoundError as e:
            if e.name in ("todo.server",):
                self.skipTest("S4 todo.server not available; item 11 cannot be verified yet")
            raise
        self.srv = make_server(self.store(), "127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        th.start()
        self.addCleanup(th.join, 5)
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()

    def test_a11_rest_post_with_due_priority(self):
        status, body = self.req("POST", "/tasks", {"title": "x", "due": "2026-12-01", "priority": "high"})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["due"], "2026-12-01")
        self.assertEqual(body["priority"], "high")
        self.assertEqual(self.store().get(body["id"])["priority"], "high")

    def test_a11_rest_invalid_due_priority_400(self):
        status, body = self.req("POST", "/tasks", {"title": "keep"})
        self.assertEqual(status, 201, body)
        tid = body["id"]
        for bad in ({"due": "bad"}, {"priority": "urgent"}):
            with self.subTest(method="POST", body=bad):
                status, b = self.req("POST", "/tasks", dict(title="x", **bad))
                self.assertEqual(status, 400, b)
                self.assertIn("error", b)
            with self.subTest(method="PATCH", body=bad):
                status, b = self.req("PATCH", f"/tasks/{tid}", bad)
                self.assertEqual(status, 400, b)
                self.assertIn("error", b)
        self.assertEqual(self.ids(self.store().list()), [tid])
        t = self.store().get(tid)
        self.assertIsNone(t["due"])
        self.assertEqual(t["priority"], "normal")

    def test_a11_rest_patch_due_null_clears(self):
        status, body = self.req("POST", "/tasks", {"title": "x", "due": "2026-12-01"})
        self.assertEqual(status, 201, body)
        status, body = self.req("PATCH", f"/tasks/{body['id']}", {"due": None})
        self.assertEqual(status, 200, body)
        self.assertIn("due", body)
        self.assertIsNone(body["due"])
        self.assertIsNone(self.store().get(body["id"])["due"])


if __name__ == "__main__":
    unittest.main()
