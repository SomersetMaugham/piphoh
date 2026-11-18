import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from todo import TaskStore
from todo.server import make_server

REPO_ROOT = Path(__file__).resolve().parents[1]


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "t.json")
        self.srv = make_server(TaskStore(self.path), port=0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmpdir.cleanup()

    def req(self, method, path, body=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = raw if raw is not None else (None if body is None else json.dumps(body))
        headers = {"Content-Type": "application/json"} if data is not None else {}
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        parsed = json.loads(payload) if payload else None
        return resp, parsed, payload

    def assertJSONError(self, resp, parsed, status):
        self.assertEqual(resp.status, status)
        self.assertTrue(resp.getheader("Content-Type", "").startswith("application/json"))
        self.assertIsInstance(parsed.get("error"), str)

    # 1-3
    def test_create_and_list(self):
        resp, body, _ = self.req("GET", "/tasks")
        self.assertEqual((resp.status, body), (200, []))
        resp, body, _ = self.req("POST", "/tasks", {"title": "Buy milk"})
        self.assertEqual(resp.status, 201)
        self.assertEqual(resp.getheader("Location"), "/tasks/1")
        self.assertTrue(resp.getheader("Content-Type").startswith("application/json"))
        self.assertEqual((body["id"], body["title"], body["done"]), (1, "Buy milk", False))
        resp, body, _ = self.req("GET", "/tasks/")
        self.assertEqual(resp.status, 200)
        self.assertEqual([t["id"] for t in body], [1])

    # 4
    def test_get_item(self):
        self.req("POST", "/tasks", {"title": "A"})
        resp, body, _ = self.req("GET", "/tasks/1?x=1")
        self.assertEqual((resp.status, body["title"]), (200, "A"))
        resp, body, _ = self.req("GET", "/tasks/99")
        self.assertJSONError(resp, body, 404)
        self.assertIn("not found", body["error"])
        self.assertEqual(body["error"], "task 99 not found")
        resp, body, _ = self.req("GET", "/tasks/abc")
        self.assertJSONError(resp, body, 404)

    # 5-6
    def test_patch(self):
        self.req("POST", "/tasks", {"title": "A"})
        resp, body, _ = self.req("PATCH", "/tasks/1", {"done": True})
        self.assertEqual((resp.status, body["done"]), (200, True))
        resp, body, _ = self.req("PATCH", "/tasks/1", {"title": "New"})
        self.assertEqual((resp.status, body["title"]), (200, "New"))
        t = TaskStore(self.path).get(1)
        self.assertEqual((t["title"], t["done"]), ("New", True))
        for bad in ({"done": "yes"}, {"color": "red"}, {}, [1]):
            resp, body, _ = self.req("PATCH", "/tasks/1", bad)
            self.assertJSONError(resp, body, 400)
        resp, body, _ = self.req("PATCH", "/tasks/1", raw="not json")
        self.assertJSONError(resp, body, 400)
        resp, body, _ = self.req("PATCH", "/tasks/99", {"done": True})
        self.assertJSONError(resp, body, 404)

    # 7
    def test_post_validation(self):
        for bad in ({}, {"title": ""}, {"title": 5}, [], {"title": "x", "bogus": 1}):
            resp, body, _ = self.req("POST", "/tasks", bad)
            self.assertJSONError(resp, body, 400)
        resp, body, _ = self.req("POST", "/tasks", raw="{nope")
        self.assertJSONError(resp, body, 400)
        resp, body, _ = self.req("POST", "/tasks")
        self.assertJSONError(resp, body, 400)
        self.assertEqual(TaskStore(self.path).list(), [])

    # 8
    def test_delete(self):
        self.req("POST", "/tasks", {"title": "A"})
        resp, body, raw = self.req("DELETE", "/tasks/1")
        self.assertEqual((resp.status, raw), (204, b""))
        resp, body, _ = self.req("GET", "/tasks/1")
        self.assertJSONError(resp, body, 404)
        resp, body, _ = self.req("DELETE", "/tasks/1")
        self.assertJSONError(resp, body, 404)

    # 9
    def test_unknown_path_and_method(self):
        resp, body, _ = self.req("GET", "/nope")
        self.assertJSONError(resp, body, 404)
        resp, body, _ = self.req("GET", "/tasks/1/x")
        self.assertJSONError(resp, body, 404)
        resp, body, _ = self.req("DELETE", "/tasks")
        self.assertJSONError(resp, body, 405)
        self.assertEqual(resp.getheader("Allow"), "GET, POST")
        resp, body, _ = self.req("PUT", "/tasks/1", {"title": "x"})
        self.assertJSONError(resp, body, 405)
        self.assertEqual(resp.getheader("Allow"), "GET, PATCH, DELETE")
        resp, body, _ = self.req("PUT", "/nope")
        self.assertJSONError(resp, body, 404)

    # 10
    def test_shared_file(self):
        TaskStore(self.path).add("lib")
        resp, body, _ = self.req("GET", "/tasks")
        self.assertEqual([t["title"] for t in body], ["lib"])
        self.req("POST", "/tasks", {"title": "http"})
        self.assertEqual([t["title"] for t in TaskStore(self.path).list()], ["lib", "http"])

    # 12
    def test_concurrent_posts(self):
        statuses, ids, lock = [], [], threading.Lock()

        def post(i):
            resp, body, _ = self.req("POST", "/tasks", {"title": f"t{i}"})
            with lock:
                statuses.append(resp.status)
                ids.append(body["id"])

        threads = [threading.Thread(target=post, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(statuses, [201] * 20)
        self.assertEqual(sorted(ids), list(range(1, 21)))


class ServeCLITest(unittest.TestCase):
    # 11
    def test_serve_subprocess(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.json")
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            proc = subprocess.Popen(
                [sys.executable, "-m", "todo", "--file", path, "serve", "--port", str(port)],
                cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
            try:
                result = {}
                reader = threading.Thread(
                    target=lambda: result.setdefault("line", proc.stdout.readline()), daemon=True)
                reader.start()
                reader.join(5)
                self.assertEqual(result.get("line", "").strip(), f"Serving on http://127.0.0.1:{port}")
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/tasks")
                resp = conn.getresponse()
                self.assertEqual((resp.status, json.loads(resp.read())), (200, []))
                conn.close()
            finally:
                proc.terminate()
                proc.wait(5)
                proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
