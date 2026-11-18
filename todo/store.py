"""JSON-file backed task store."""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from todo.errors import StoreError, TaskNotFound, ValidationError

FILE_VERSION = 1
DEFAULT_FILENAME = ".todo.json"
ENV_VAR = "TODO_FILE"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_title(title) -> str:
    if not isinstance(title, str):
        raise ValidationError("title must be a string")
    title = title.strip()
    if not title:
        raise ValidationError("title must not be empty")
    return title


def _resolve_path(path) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env)
    return Path(os.path.expanduser("~")) / DEFAULT_FILENAME


class TaskStore:
    """Persist tasks in a JSON file. Every call re-reads the file."""

    CREATE_FIELDS = ("title",)
    UPDATE_FIELDS = ("title", "done")

    def __init__(self, path=None):
        self.path = _resolve_path(path)
        self._lock = threading.Lock()

    # -- file I/O -----------------------------------------------------------
    def _empty(self) -> dict:
        return {"version": FILE_VERSION, "next_id": 1, "tasks": []}

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            return self._empty()
        except OSError as exc:
            raise StoreError(f"cannot read {self.path}: {exc.strerror or exc}") from exc
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise StoreError(f"invalid JSON in {self.path}: {exc}") from exc
        self._check_structure(data)
        return data

    def _check_structure(self, data) -> None:
        def bad(why):
            raise StoreError(f"invalid store file {self.path}: {why}")

        if not isinstance(data, dict):
            bad("top level must be an object")
        tasks = data.get("tasks")
        next_id = data.get("next_id")
        if not isinstance(tasks, list):
            bad("'tasks' must be a list")
        if not isinstance(next_id, int) or isinstance(next_id, bool) or next_id < 1:
            bad("'next_id' must be a positive integer")
        for t in tasks:
            if not isinstance(t, dict):
                bad("each task must be an object")
            tid = t.get("id")
            if not isinstance(tid, int) or isinstance(tid, bool):
                bad("task 'id' must be an integer")
            if not isinstance(t.get("title"), str) or not isinstance(t.get("done"), bool):
                bad(f"task {tid} has invalid 'title' or 'done'")
            if tid >= next_id:
                bad(f"task id {tid} is not below 'next_id'")

    def _save(self, data: dict) -> None:
        parent = self.path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                    fh.write("\n")
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise StoreError(f"cannot write {self.path}: {exc.strerror or exc}") from exc

    @staticmethod
    def _find(data: dict, task_id) -> dict:
        for t in data["tasks"]:
            if t["id"] == task_id and type(task_id) is not bool:
                return t
        raise TaskNotFound(task_id)

    # -- validation -----------------------------------------------------------
    def _validate_update(self, fields: dict) -> dict:
        if not fields:
            raise ValidationError("no fields to update")
        unknown = sorted(k for k in fields if k not in self.UPDATE_FIELDS)
        if unknown:
            raise ValidationError(f"unknown field(s): {', '.join(unknown)}")
        clean = {}
        if "title" in fields:
            clean["title"] = _clean_title(fields["title"])
        if "done" in fields:
            if not isinstance(fields["done"], bool):
                raise ValidationError("done must be a boolean")
            clean["done"] = fields["done"]
        return clean

    # -- public API ---------------------------------------------------------
    def add(self, title, **fields) -> dict:
        if fields:
            raise ValidationError(f"unknown field(s): {', '.join(sorted(fields))}")
        title = _clean_title(title)
        with self._lock:
            data = self._load()
            task = {"id": data["next_id"], "title": title, "done": False, "created": _now()}
            data["tasks"].append(task)
            data["next_id"] += 1
            self._save(data)
            return dict(task)

    def list(self) -> list:
        with self._lock:
            data = self._load()
        return [dict(t) for t in sorted(data["tasks"], key=lambda t: t["id"])]

    def get(self, task_id) -> dict:
        with self._lock:
            data = self._load()
        return dict(self._find(data, task_id))

    def complete(self, task_id) -> dict:
        with self._lock:
            data = self._load()
            task = self._find(data, task_id)
            if not task["done"]:
                task["done"] = True
                self._save(data)
            return dict(task)

    def update(self, task_id, **fields) -> dict:
        clean = self._validate_update(fields)
        with self._lock:
            data = self._load()
            task = self._find(data, task_id)
            task.update(clean)
            self._save(data)
            return dict(task)

    def delete(self, task_id) -> dict:
        with self._lock:
            data = self._load()
            task = self._find(data, task_id)
            data["tasks"].remove(task)
            self._save(data)
            return dict(task)
