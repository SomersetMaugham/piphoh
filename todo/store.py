"""JSON-file backed task store."""

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from todo.errors import StoreError, TaskNotFound, ValidationError

FILE_VERSION = 1
DEFAULT_FILENAME = ".todo.json"
ENV_VAR = "TODO_FILE"
CREATED_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


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
    def _validate_create(self, title, fields: dict) -> dict:
        """Shared create-path validator (used by add and restore).

        Returns the cleaned field dict including ``title``. S1 semantics: any
        extra field is unknown. S3 extends this helper for due/priority.
        """
        unknown = sorted(k for k in fields if k == "title" or k not in self.CREATE_FIELDS)
        if unknown:
            raise ValidationError(f"unknown field(s): {', '.join(unknown)}")
        return {"title": _clean_title(title)}

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
        clean = self._validate_create(title, fields)
        with self._lock:
            data = self._load()
            task = {"id": data["next_id"], "title": clean.pop("title"), "done": False,
                    "created": _now()}
            task.update(clean)
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

    def restore(self, records) -> dict:
        """Insert tasks from ``records`` (e.g. a CSV import), all-or-nothing.

        Each record is a dict with ``title`` and optional ``id`` (positive int
        or None -> new id), ``done`` (bool, default False), ``created``
        (``YYYY-MM-DDTHH:MM:SSZ`` or None -> now) plus create fields accepted by
        ``_validate_create``. A record whose id already exists in the store or
        repeats an earlier record's id is skipped (never overwritten). Any
        invalid record raises ValidationError (message prefixed ``record <n>:``,
        1-based) and nothing is written. Explicit ids are placed first; blank-id
        records then get fresh ids above every existing and imported id.
        Returns ``{"imported": [ids], "skipped": [ids]}``.
        """
        prepared = []
        for n, rec in enumerate(records, 1):
            try:
                prepared.append(self._prepare_record(rec))
            except ValidationError as exc:
                err = ValidationError(f"record {n}: {exc}")
                err.record_index = n - 1  # 0-based position in records
                err.reason = str(exc)
                raise err from exc
        with self._lock:
            data = self._load()
            taken = {t["id"] for t in data["tasks"]}
            placed = {}  # index -> task
            skipped = []
            for i, (tid, task) in enumerate(prepared):
                if tid is None:
                    continue
                if tid in taken:
                    skipped.append(tid)
                    continue
                taken.add(tid)
                placed[i] = dict(task, id=tid)
            next_id = max([data["next_id"]] + [t["id"] + 1 for t in placed.values()])
            for i, (tid, task) in enumerate(prepared):
                if tid is None:
                    placed[i] = dict(task, id=next_id)
                    next_id += 1
            new_tasks = [placed[i] for i in sorted(placed)]
            imported = [t["id"] for t in new_tasks]
            if new_tasks:
                data["tasks"].extend(new_tasks)
                data["tasks"].sort(key=lambda t: t["id"])
                data["next_id"] = next_id
                self._save(data)
            return {"imported": imported, "skipped": skipped}

    def _prepare_record(self, rec) -> tuple:
        if not isinstance(rec, dict):
            raise ValidationError("record must be a dict")
        rec = dict(rec)
        tid = rec.pop("id", None)
        if tid is not None and (type(tid) is not int or tid < 1):
            raise ValidationError("id must be a positive integer")
        done = rec.pop("done", False)
        if not isinstance(done, bool):
            raise ValidationError("done must be a boolean")
        created = rec.pop("created", None)
        if created is None:
            created = _now()
        elif not isinstance(created, str) or not CREATED_RE.match(created):
            raise ValidationError("created must look like YYYY-MM-DDTHH:MM:SSZ")
        if "title" not in rec:
            raise ValidationError("title is required")
        clean = self._validate_create(rec.pop("title"), rec)
        task = {"id": tid, "title": clean.pop("title"), "done": done, "created": created}
        task.update(clean)
        return tid, task
