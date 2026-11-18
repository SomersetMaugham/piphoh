"""Acceptance tests for slice S4 (REST API).

Test names carry the contract's Acceptance item number (a1..a12).
Each test starts a real server via todo.server.make_server(TaskStore(tmp), port=0)
in a daemon thread and talks to it with http.client. Stdlib only; no imports
through the ``tests.`` prefix; no nested test-suite runs.
"""
import http.client
import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load():
    """Import lazily so a missing module fails each test, not collection."""
    from todo import TaskStore
    from todo.server import make_server
    return TaskStore, make_server


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name) / "tasks.json"
        self.TaskStore, make_server = _load()
        self.srv = make_server(self.TaskStore(self.tmp), "127.0.0.1", port=0)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        srv = getattr(self, "srv", None)
        if srv is not None:
            srv.shutdown()
            srv.server_close()
            self.thread.join(timeout=5)

    # -- helpers ---------------------------------------------------------
    def request(self, method, path, body=None, raw=None):
        """Return (status, headers-dict-lowercased, body-bytes)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {}
            data = None
            if raw is not None:
                data = raw if isinstance(raw, bytes) else raw.encode()
            elif body is not None:
                data = json.dumps(body).encode()
            if data is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(data))
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, hdrs, payload
        finally:
            conn.close()

    def json_of(self, payload):
        return json.loads(payload.decode("utf-8"))

    def assertJsonError(self, status, hdrs, payload, expected_status, contains=None):
        self.assertEqual(status, expected_status, payload)
        self.assertTrue(hdrs.get("content-type", "").startswith("application/json"),
                        "error Content-Type: %r" % hdrs.get("content-type"))
        obj = self.json_of(payload)
        self.assertIsInstance(obj, dict)
        self.assertIn("error", obj)
        self.assertIsInstance(obj["error"], str)
        if contains:
            self.assertIn(contains, obj["error"])

    def assertTaskSubset(self, task, **expected):
        self.assertIsInstance(task, dict)
        for k, v in expected.items():
            self.assertIn(k, task)
            self.assertEqual(task[k], v, "key %r" % k)

    def post_task(self, title="Buy milk"):
        status, hdrs, payload = self.request("POST", "/tasks", {"title": title})
        self.assertEqual(status, 201, payload)
        return self.json_of(payload)


class TestA1PostThenList(ServerTestCase):
    def test_a1_post_then_list(self):
        status, _, payload = self.request("POST", "/tasks", {"title": "Buy milk"})
        self.assertEqual(status, 201, payload)
        self.assertTaskSubset(self.json_of(payload), id=1, title="Buy milk", done=False)
        status, _, payload = self.request("GET", "/tasks")
        self.assertEqual(status, 200, payload)
        tasks = self.json_of(payload)
        self.assertIsInstance(tasks, list)
        self.assertEqual(len(tasks), 1)
        self.assertTaskSubset(tasks[0], id=1, title="Buy milk", done=False)


class TestA2PostHeaders(ServerTestCase):
    def test_a2_post_location_and_content_type(self):
        status, hdrs, payload = self.request("POST", "/tasks", {"title": "Buy milk"})
        self.assertEqual(status, 201, payload)
        self.assertEqual(hdrs.get("location"), "/tasks/1")
        self.assertTrue(hdrs.get("content-type", "").startswith("application/json"),
                        hdrs.get("content-type"))


class TestA3EmptyList(ServerTestCase):
    def test_a3_get_tasks_empty(self):
        status, hdrs, payload = self.request("GET", "/tasks")
        self.assertEqual(status, 200, payload)
        self.assertTrue(hdrs.get("content-type", "").startswith("application/json"))
        self.assertEqual(self.json_of(payload), [])

    def test_a3_trailing_slash_and_query_tolerated(self):
        # Interface: "/tasks/" == "/tasks"; query strings ignored.
        for path in ("/tasks/", "/tasks?x=1"):
            with self.subTest(path=path):
                status, _, payload = self.request("GET", path)
                self.assertEqual(status, 200, payload)
                self.assertEqual(self.json_of(payload), [])


class TestA4GetOne(ServerTestCase):
    def test_a4_get_existing(self):
        self.post_task("Buy milk")
        status, hdrs, payload = self.request("GET", "/tasks/1")
        self.assertEqual(status, 200, payload)
        self.assertTrue(hdrs.get("content-type", "").startswith("application/json"))
        self.assertTaskSubset(self.json_of(payload), id=1, title="Buy milk", done=False)

    def test_a4_get_missing_404(self):
        self.post_task()
        self.assertJsonError(*self.request("GET", "/tasks/99"), 404, contains="not found")

    def test_a4_get_non_integer_id_404(self):
        self.post_task()
        status, _, payload = self.request("GET", "/tasks/abc")
        self.assertEqual(status, 404, payload)


class TestA5Patch(ServerTestCase):
    def test_a5_patch_done_and_title_persisted(self):
        self.post_task("Buy milk")
        status, _, payload = self.request("PATCH", "/tasks/1", {"done": True})
        self.assertEqual(status, 200, payload)
        self.assertTaskSubset(self.json_of(payload), id=1, done=True)
        status, _, payload = self.request("PATCH", "/tasks/1", {"title": "New"})
        self.assertEqual(status, 200, payload)
        self.assertTaskSubset(self.json_of(payload), id=1, title="New", done=True)
        self.assertTaskSubset(self.TaskStore(self.tmp).get(1), id=1, title="New", done=True)


class TestA6PatchErrors(ServerTestCase):
    def test_a6_patch_bad_bodies_400(self):
        self.post_task("Buy milk")
        cases = [
            ("done not bool", {"done": "yes"}, None),
            ("unknown key", {"color": "red"}, None),
            ("empty object", {}, None),
            ("invalid json", None, "not json"),
        ]
        for name, body, raw in cases:
            with self.subTest(case=name):
                self.assertJsonError(*self.request("PATCH", "/tasks/1", body, raw=raw), 400)
        # task unchanged
        self.assertTaskSubset(self.TaskStore(self.tmp).get(1), title="Buy milk", done=False)

    def test_a6_patch_missing_404(self):
        self.post_task()
        self.assertJsonError(*self.request("PATCH", "/tasks/99", {"done": True}), 404)


class TestA7PostErrors(ServerTestCase):
    def test_a7_post_bad_bodies_400_store_unchanged(self):
        cases = [
            ("empty object", {}, None),
            ("empty title", {"title": ""}, None),
            ("non-str title", {"title": 5}, None),
            ("array", [], None),
            ("unknown key", {"title": "x", "bogus": 1}, None),
            ("invalid json", None, "{not json"),
        ]
        for name, body, raw in cases:
            with self.subTest(case=name):
                self.assertJsonError(*self.request("POST", "/tasks", body, raw=raw), 400)
        self.assertEqual(self.TaskStore(self.tmp).list(), [])
        status, _, payload = self.request("GET", "/tasks")
        self.assertEqual(status, 200)
        self.assertEqual(self.json_of(payload), [])


class TestA8Delete(ServerTestCase):
    def test_a8_delete_then_404(self):
        self.post_task()
        status, _, payload = self.request("DELETE", "/tasks/1")
        self.assertEqual(status, 204)
        self.assertEqual(payload, b"")
        self.assertJsonError(*self.request("GET", "/tasks/1"), 404, contains="not found")
        self.assertJsonError(*self.request("DELETE", "/tasks/1"), 404)


class TestA9RoutingErrors(ServerTestCase):
    def test_a9_unknown_path_404_json(self):
        self.assertJsonError(*self.request("GET", "/nope"), 404)

    def test_a9_delete_collection_405_with_allow(self):
        status, hdrs, payload = self.request("DELETE", "/tasks")
        self.assertEqual(status, 405, payload)
        self.assertIn("allow", hdrs)
        allow = {m.strip().upper() for m in hdrs["allow"].split(",")}
        self.assertTrue({"GET", "POST"} <= allow, hdrs["allow"])
        self.assertNotIn("DELETE", allow)

    def test_a9_put_item_405(self):
        self.post_task()
        status, hdrs, payload = self.request("PUT", "/tasks/1", {"title": "x"})
        self.assertEqual(status, 405, payload)
        # Interface: wrong method on known path -> 405 with Allow header.
        self.assertIn("allow", hdrs)
        self.assertNotIn("PUT", hdrs["allow"].upper())


class TestA10SharedFile(ServerTestCase):
    def test_a10_library_write_visible_over_http(self):
        self.TaskStore(self.tmp).add("From library")
        status, _, payload = self.request("GET", "/tasks/1")
        self.assertEqual(status, 200, payload)
        self.assertTaskSubset(self.json_of(payload), id=1, title="From library")

    def test_a10_http_write_visible_in_library(self):
        self.TaskStore(self.tmp).add("First")
        self.post_task("From HTTP")
        self.assertTaskSubset(self.TaskStore(self.tmp).get(2), id=2, title="From HTTP")
        self.request("PATCH", "/tasks/1", {"done": True})
        self.assertTrue(self.TaskStore(self.tmp).get(1)["done"])
        self.TaskStore(self.tmp).delete(2)
        status, _, _ = self.request("GET", "/tasks/2")
        self.assertEqual(status, 404)


class TestA11CliServe(unittest.TestCase):
    def _free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_a11_cli_serve(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        tmp = Path(tmpdir.name) / "tasks.json"
        port = self._free_port()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("PYTHONUNBUFFERED", None)  # the server must flush itself
        proc = subprocess.Popen(
            [sys.executable, "-m", "todo", "--file", str(tmp), "serve", "--port", str(port)],
            cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )

        def cleanup():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()
        self.addCleanup(cleanup)

        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
        expected = "Serving on http://127.0.0.1:%d" % port
        try:
            line = lines.get(timeout=5)
        except queue.Empty:
            self.fail("no stdout line within 5 s (exit=%r)" % proc.poll())
        if not line:
            proc.wait(timeout=5)
            self.fail("process exited %r without output; stderr:\n%s"
                      % (proc.returncode, proc.stderr.read()))
        self.assertEqual(line.strip(), expected)

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", "/tasks")
            resp = conn.getresponse()
            body = resp.read()
        finally:
            conn.close()
        self.assertEqual(resp.status, 200, body)
        self.assertEqual(json.loads(body), [])


class TestA12Concurrency(ServerTestCase):
    def test_a12_concurrent_posts(self):
        n = 20
        barrier = threading.Barrier(n)
        results = [None] * n
        errors = []

        def worker(i):
            try:
                barrier.wait(timeout=10)
                results[i] = self.request("POST", "/tasks", {"title": "t%d" % i})
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        statuses = [r[0] for r in results]
        self.assertEqual(statuses, [201] * n)
        ids = sorted(self.json_of(r[2])["id"] for r in results)
        self.assertEqual(ids, list(range(1, n + 1)))
        stored = [t["id"] for t in self.TaskStore(self.tmp).list()]
        self.assertEqual(stored, list(range(1, n + 1)))


if __name__ == "__main__":
    unittest.main()
