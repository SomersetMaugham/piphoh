"""CSV export/import (``todo export FILE`` / ``todo import FILE``)."""

import csv

from todo.errors import StoreError, ValidationError
from todo.store import TaskStore

COLUMNS = ("id", "title", "done", "created", "due", "priority")
_TRUE = {"true", "1"}
_FALSE = {"false", "0"}


def _cell(value) -> str:
    return "" if value is None else str(value)


def export_csv(store: TaskStore, path) -> int:
    """Write every task to ``path`` (overwriting it); return the row count."""
    tasks = store.list()
    try:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(COLUMNS)
            for t in tasks:
                writer.writerow([
                    t["id"],
                    t["title"],
                    "true" if t["done"] else "false",
                    t["created"],
                    _cell(t.get("due")),
                    _cell(t.get("priority")),
                ])
    except OSError as exc:
        raise StoreError(f"cannot write {path}: {exc.strerror or exc}") from exc
    return len(tasks)


def _read_rows(path) -> list:
    """Return [(line_number, cells), ...] including the header row."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            rows = []
            while True:
                start = reader.line_num + 1
                try:
                    cells = next(reader)
                except StopIteration:
                    break
                if cells:  # skip blank lines
                    rows.append((start, cells))
            return rows
    except csv.Error as exc:
        raise ValidationError(f"{path}: invalid CSV: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise StoreError(f"cannot read {path}: not valid UTF-8") from exc
    except OSError as exc:
        raise StoreError(f"cannot read {path}: {exc.strerror or exc}") from exc


def _parse_row(header, cells) -> dict:
    if len(cells) > len(header):
        raise ValidationError(f"expected {len(header)} fields, got {len(cells)}")
    values = dict(zip(header, cells))
    rec = {"title": values.get("title", "")}
    raw_id = values.get("id", "").strip()
    if raw_id:
        try:
            tid = int(raw_id)
        except ValueError:
            raise ValidationError(f"id must be a positive integer, got {raw_id!r}") from None
        if tid < 1:
            raise ValidationError(f"id must be a positive integer, got {raw_id!r}")
        rec["id"] = tid
    raw_done = values.get("done", "").strip().lower()
    if raw_done:
        if raw_done in _TRUE:
            rec["done"] = True
        elif raw_done in _FALSE:
            rec["done"] = False
        else:
            raise ValidationError(f"done must be true/false/1/0, got {values['done']!r}")
    raw_created = values.get("created", "").strip()
    if raw_created:
        rec["created"] = raw_created
    for key in ("due", "priority"):
        raw = values.get(key, "")
        if raw.strip():
            rec[key] = raw.strip()
    return rec


def import_csv(store: TaskStore, path) -> dict:
    """Load tasks from ``path``; return ``{"imported": n, "skipped": m}``."""
    rows = _read_rows(path)
    if not rows:
        raise ValidationError(f"{path}: empty file (no header)")
    header_line, header = rows[0]
    header = [h.strip() for h in header]
    seen = set()
    for name in header:
        if name not in COLUMNS:
            raise ValidationError(f"{path}:{header_line}: unknown column {name!r}")
        if name in seen:
            raise ValidationError(f"{path}:{header_line}: duplicate column {name!r}")
        seen.add(name)
    if "title" not in seen:
        raise ValidationError(f"{path}:{header_line}: header must contain a 'title' column")
    records, lines = [], []
    for line, cells in rows[1:]:
        try:
            records.append(_parse_row(header, cells))
        except ValidationError as exc:
            raise ValidationError(f"{path}:{line}: {exc}") from exc
        lines.append(line)
    try:
        result = store.restore(records)
    except ValidationError as exc:
        idx = getattr(exc, "record_index", None)
        if idx is None:
            raise
        raise ValidationError(f"{path}:{lines[idx]}: {exc.reason}") from exc
    return {"imported": len(result["imported"]), "skipped": len(result["skipped"])}


def _store(args) -> TaskStore:
    return TaskStore(getattr(args, "file", None))


def cmd_export(args) -> int:
    n = export_csv(_store(args), args.path)  # TodoError -> cli.main prints "error:", exit 1
    print(f"Exported {n} tasks to {args.path}")
    return 0


def cmd_import(args) -> int:
    r = import_csv(_store(args), args.path)
    print(f"Imported {r['imported']} tasks, skipped {r['skipped']} duplicates")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("export", help="export all tasks to a CSV file")
    p.add_argument("path", metavar="FILE", help="CSV file to write (overwritten)")
    p.set_defaults(func=cmd_export)

    p = subparsers.add_parser("import", help="import tasks from a CSV file")
    p.add_argument("path", metavar="FILE", help="CSV file to read")
    p.set_defaults(func=cmd_import)
