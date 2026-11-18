"""Local JSON REST API over the task store (stdlib ``http.server``).

Routes: GET/POST /tasks, GET/PATCH/DELETE /tasks/<id>.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from todo.errors import TaskNotFound, TodoError, ValidationError
from todo.store import TaskStore

COLLECTION_METHODS = ("GET", "POST")
ITEM_METHODS = ("GET", "PATCH", "DELETE")


class _HTTPError(Exception):
    def __init__(self, status: int, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers or {}


class TodoRequestHandler(BaseHTTPRequestHandler):
    server_version = "todo"

    # -- plumbing -------------------------------------------------------------
    def log_message(self, format, *args):  # noqa: A002 (stdlib signature)
        if getattr(self.server, "log_requests", False):
            super().log_message(format, *args)

    def _send_json(self, status: int, payload, headers: dict | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_json_object(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise _HTTPError(400, "invalid Content-Length")
        if length < 0:
            raise _HTTPError(400, "invalid Content-Length")
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise _HTTPError(400, "request body must be valid JSON")
        if not isinstance(data, dict):
            raise _HTTPError(400, "request body must be a JSON object")
        return data

    @staticmethod
    def _check_keys(data: dict, allowed) -> None:
        unknown = sorted(k for k in data if k not in allowed)
        if unknown:
            raise _HTTPError(400, f"unknown field(s): {', '.join(unknown)}")

    def _route(self):
        """Return (allowed_methods, task_id_or_None) or raise 404."""
        path = urlsplit(self.path).path
        if len(path) > 1:
            path = path.rstrip("/")
        parts = path.split("/")
        if parts[:2] == ["", "tasks"]:
            if len(parts) == 2:
                return COLLECTION_METHODS, None
            if len(parts) == 3 and parts[2].isascii() and parts[2].isdigit():
                return ITEM_METHODS, int(parts[2])
        raise _HTTPError(404, "not found")

    def _dispatch(self) -> None:
        try:
            allowed, task_id = self._route()
            method = self.command
            if method not in allowed:
                raise _HTTPError(405, f"method {method} not allowed",
                                 {"Allow": ", ".join(allowed)})
            if task_id is None:
                if method == "GET":
                    self._send_json(200, self._call(lambda s: s.list()))
                else:
                    self._create()
            elif method == "GET":
                self._send_json(200, self._call(lambda s: s.get(task_id)))
            elif method == "PATCH":
                data = self._read_json_object()
                self._check_keys(data, self.server.store.UPDATE_FIELDS)
                self._send_json(200, self._call(lambda s: s.update(task_id, **data)))
            else:  # DELETE
                self._call(lambda s: s.delete(task_id))
                self._send_empty(204)
        except _HTTPError as exc:
            self._send_json(exc.status, {"error": exc.message}, exc.headers)
        except Exception as exc:  # pragma: no cover - defensive
            self.log_error("internal error: %r", exc)
            self._send_json(500, {"error": "internal server error"})

    def _create(self) -> None:
        data = self._read_json_object()
        if "title" not in data:
            raise _HTTPError(400, "missing field: title")
        self._check_keys(data, self.server.store.CREATE_FIELDS)
        fields = dict(data)
        title = fields.pop("title")
        task = self._call(lambda s: s.add(title, **fields))
        self._send_json(201, task, {"Location": f"/tasks/{task['id']}"})

    def _call(self, fn):
        """Run ``fn(store)`` under the server lock, mapping store errors to HTTP."""
        try:
            with self.server.store_lock:
                return fn(self.server.store)
        except ValidationError as exc:
            raise _HTTPError(400, str(exc))
        except TaskNotFound as exc:
            raise _HTTPError(404, str(exc))
        except TodoError as exc:
            raise _HTTPError(500, str(exc))

    do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = do_OPTIONS = _dispatch


class TodoHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128  # default 5 drops connections under concurrent clients


def make_server(store: TaskStore, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Return a bound (not yet serving) HTTP server exposing ``store``."""
    server = TodoHTTPServer((host, port), TodoRequestHandler)
    server.store = store
    server.store_lock = threading.Lock()
    server.log_requests = False
    return server


def _serve(args) -> int:
    store = TaskStore(getattr(args, "file", None))
    try:
        server = make_server(store, args.host, args.port)
    except OSError as exc:
        print(f"error: cannot listen on {args.host}:{args.port}: {exc.strerror or exc}",
              file=sys.stderr)
        return 1
    server.log_requests = True
    host, port = server.server_address[:2]
    print(f"Serving on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("serve", help="run the REST API server")
    p.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    p.add_argument("--host", default="127.0.0.1", help="host (default 127.0.0.1)")
    p.set_defaults(func=_serve)
