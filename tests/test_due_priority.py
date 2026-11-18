"""Dev-owned tests for S3 (due/priority, filter/sort, CLI suffix)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from todo.commands import format_task
from todo.csvio import export_csv, import_csv
from todo.errors import ValidationError
from todo.store import TaskStore


class DuePriorityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-s3dev-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.s = TaskStore(self.tmp / "t.json")

    def test_due_format_edge_cases(self):
        for bad in ("2026-12-01\n", "２０２６-12-01", "2026-12-01T00:00", " 2026-12-01", True):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.s.add("x", due=bad)
        self.assertEqual(self.s.add("leap", due="2028-02-29")["due"], "2028-02-29")

    def test_validate_create_returns_clean_dict(self):
        self.assertEqual(self.s._validate_create(" t ", {}),
                         {"title": "t", "due": None, "priority": "normal"})
        with self.assertRaises(ValidationError):
            self.s._validate_create("t", {"title": "dup"})

    def test_update_legacy_task_backfills(self):
        p = self.s.path
        p.write_text(json.dumps({"version": 1, "next_id": 2, "tasks": [
            {"id": 1, "title": "old", "done": False, "created": "2026-01-01T00:00:00Z"}]}))
        t = self.s.update(1, priority="high")
        self.assertEqual((t["due"], t["priority"]), (None, "high"))
        self.assertEqual(self.s.complete(1)["due"], None)

    def test_format_task_suffix(self):
        base = {"id": 1, "title": "T", "done": False}
        self.assertEqual(format_task(dict(base, due=None, priority="normal")), "1 [ ] T")
        self.assertEqual(format_task(dict(base, due="2026-12-01", priority="normal")),
                         "1 [ ] T (due 2026-12-01)")
        self.assertEqual(format_task(dict(base, due=None, priority="low")), "1 [ ] T (priority low)")
        self.assertEqual(format_task(dict(base, done=True, due="2026-12-01", priority="high")),
                         "1 [x] T (due 2026-12-01, priority high)")

    def test_csv_round_trip_with_due_priority(self):
        self.s.add("a", due="2026-12-01", priority="high")
        self.s.add("b")
        self.s.add("c", priority="low")
        csv_path = self.tmp / "out.csv"
        export_csv(self.s, csv_path)
        other = TaskStore(self.tmp / "b.json")
        import_csv(other, csv_path)
        self.assertEqual(other.list(), self.s.list())


if __name__ == "__main__":
    unittest.main()
