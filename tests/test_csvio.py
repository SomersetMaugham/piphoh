"""Dev-owned tests for S5 CSV export/import (store.restore, todo.csvio, CLI)."""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from todo import StoreError, TaskStore, ValidationError
from todo.csvio import COLUMNS, export_csv, import_csv

ROOT = Path(__file__).resolve().parent.parent


def run_cli(store_path, *args, use_env=False):
    """Run the CLI against store_path via --file (default) or TODO_FILE."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("TODO_FILE", None)
    if use_env:
        env["TODO_FILE"] = str(store_path)
        argv = list(args)
    else:
        argv = ["--file", str(store_path), *args]
    return subprocess.run([sys.executable, "-m", "todo", *argv], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=30)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.a = TaskStore(self.tmp / "a.json")
        self.b = TaskStore(self.tmp / "b.json")
        self.csv = self.tmp / "out.csv"

    def tearDown(self):
        self._tmp.cleanup()

    def write_csv(self, text, bom=False):
        self.csv.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


class TestLibrary(Base):
    def test_round_trip(self):
        self.a.add("Buy milk")
        self.a.add('Say "hi", world\nsecond line')
        self.a.complete(2)
        self.assertEqual(export_csv(self.a, self.csv), 2)
        self.assertEqual(import_csv(self.b, self.csv), {"imported": 2, "skipped": 0})
        self.assertEqual(self.b.list(), self.a.list())
        self.assertEqual(self.b.add("next")["id"], 3)

    def test_header_and_cells(self):
        self.a.add("x")
        self.a.complete(1)
        export_csv(self.a, self.csv)
        raw = self.csv.read_bytes()
        self.assertTrue(raw.startswith(b"id,title,done,created,due,priority\r\n"))
        with self.csv.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[0]["done"], "true")
        self.assertEqual((rows[0]["due"], rows[0]["priority"]), ("", "normal"))  # S3 merged
        self.assertEqual(tuple(rows[0]), COLUMNS)

    def test_empty_store_header_only(self):
        self.assertEqual(export_csv(self.a, self.csv), 0)
        self.assertEqual(self.csv.read_bytes(), b"id,title,done,created,due,priority\r\n")

    def test_duplicates_skipped(self):
        self.a.add("one")
        self.a.add("two")
        export_csv(self.a, self.csv)
        import_csv(self.b, self.csv)
        before = self.b.path.read_bytes()
        self.assertEqual(import_csv(self.b, self.csv), {"imported": 0, "skipped": 2})
        self.assertEqual(self.b.path.read_bytes(), before)

    def test_duplicate_within_file(self):
        self.write_csv("id,title\n5,first\n5,second\n")
        self.assertEqual(import_csv(self.b, self.csv), {"imported": 1, "skipped": 1})
        self.assertEqual(self.b.get(5)["title"], "first")
        self.assertEqual(self.b.add("n")["id"], 6)

    def test_existing_never_overwritten(self):
        self.b.add("keep")
        self.write_csv("id,title\n1,replace\n")
        self.assertEqual(import_csv(self.b, self.csv), {"imported": 0, "skipped": 1})
        self.assertEqual(self.b.get(1)["title"], "keep")

    def test_title_only_gets_new_ids(self):
        for t in "abc":
            self.b.add(t)
        self.write_csv("title\nx\ny\nz\n")
        self.assertEqual(import_csv(self.b, self.csv)["imported"], 3)
        tasks = self.b.list()[3:]
        self.assertEqual([t["id"] for t in tasks], [4, 5, 6])
        now = datetime.now(timezone.utc)
        for t in tasks:
            self.assertFalse(t["done"])
            created = datetime.strptime(t["created"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            self.assertLess(abs((now - created).total_seconds()), 5)
        self.assertEqual(self.b.add("n")["id"], 7)

    def test_blank_ids_do_not_collide_with_explicit(self):
        self.write_csv("id,title\n,blank\n1,explicit\n")
        self.assertEqual(import_csv(self.b, self.csv), {"imported": 2, "skipped": 0})
        self.assertEqual(self.b.get(1)["title"], "explicit")
        self.assertEqual(self.b.get(2)["title"], "blank")

    def test_high_id_bumps_next_id(self):
        self.write_csv("id,title\n10,ten\n")
        import_csv(self.b, self.csv)
        self.assertEqual(self.b.add("n")["id"], 11)

    def test_done_variants(self):
        self.write_csv("title,done\na,TRUE\nb,0\nc,1\nd,\n")
        import_csv(self.b, self.csv)
        self.assertEqual([t["done"] for t in self.b.list()], [True, False, True, False])

    def test_invalid_rows_all_or_nothing(self):
        cases = {
            "id,title\n1,ok\nabc,x\n": 3,
            "id,title\n1,ok\n0,x\n": 3,
            "title,done\nok,true\nx,maybe\n": 3,
            "title,created\nok,\nx,yesterday\n": 3,
            "title,done\nA,true\n,false\n": 3,
            "title,due\nok,\nx,2026-02-30\n": 3,  # S3: not a real calendar date
            "title,priority\nx,urgent\n": 2,  # S3: bad priority
        }
        self.b.add("existing")
        before = self.b.path.read_bytes()
        for text, line in cases.items():
            with self.subTest(text=text):
                self.write_csv(text)
                with self.assertRaises(ValidationError) as cm:
                    import_csv(self.b, self.csv)
                self.assertIn(f"{self.csv}:{line}:", str(cm.exception))
                self.assertEqual(self.b.path.read_bytes(), before)

    def test_blank_title_message(self):
        self.write_csv("title,done\nA,true\n,false\n")
        with self.assertRaises(ValidationError) as cm:
            import_csv(self.b, self.csv)
        self.assertEqual(str(cm.exception), f"{self.csv}:3: title must not be empty")

    def test_bad_headers(self):
        for text in ("done\ntrue\n", "title,color\nx,red\n", "title,title\nx,y\n", ""):
            with self.subTest(text=text):
                self.write_csv(text)
                with self.assertRaises(ValidationError):
                    import_csv(self.b, self.csv)
        self.assertFalse(self.b.path.exists())

    def test_missing_file(self):
        missing = self.tmp / "nope.csv"
        with self.assertRaises(StoreError) as cm:
            import_csv(self.b, missing)
        self.assertIn(str(missing), str(cm.exception))

    def test_export_bad_dir(self):
        with self.assertRaises(StoreError):
            export_csv(self.a, self.tmp / "no" / "dir" / "x.csv")

    def test_bom_and_unicode(self):
        self.write_csv("title\nCafé ☕ 日本\n", bom=True)
        self.assertEqual(import_csv(self.b, self.csv)["imported"], 1)
        self.assertEqual(self.b.get(1)["title"], "Café ☕ 日本")
        out = self.tmp / "o.csv"
        export_csv(self.b, out)
        c = TaskStore(self.tmp / "c.json")
        import_csv(c, out)
        self.assertEqual(c.list(), self.b.list())

    def test_restore_direct(self):
        r = self.b.restore([{"id": 3, "title": "x", "done": True, "created": "2026-01-01T00:00:00Z"},
                            {"title": "y"}])
        self.assertEqual(r, {"imported": [3, 4], "skipped": []})
        with self.assertRaises(ValidationError):
            self.b.restore([{"title": "ok"}, {"title": "x", "done": "true"}])
        self.assertEqual(len(self.b.list()), 2)
        with self.assertRaises(ValidationError):
            self.b.restore([{"title": "x", "bogus": 1}])


class TestCLI(Base):
    def test_export_import(self):
        self.a.add("Buy milk")
        self.a.add("Two")
        self.a.complete(2)
        r = run_cli(self.a.path, "export", str(self.csv))
        self.assertEqual((r.returncode, r.stdout), (0, f"Exported 2 tasks to {self.csv}\n"))
        r = run_cli(self.b.path, "import", str(self.csv))
        self.assertEqual((r.returncode, r.stdout), (0, "Imported 2 tasks, skipped 0 duplicates\n"))
        self.assertEqual(self.b.list(), self.a.list())
        r = run_cli(self.b.path, "import", str(self.csv))
        self.assertEqual(r.stdout, "Imported 0 tasks, skipped 2 duplicates\n")

    def test_errors(self):
        self.write_csv("title,done\nA,true\n,false\n")
        r = run_cli(self.b.path, "import", str(self.csv))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr, f"error: {self.csv}:3: title must not be empty\n")
        self.assertFalse(self.b.path.exists())
        r = run_cli(self.b.path, "import", str(self.tmp / "missing.csv"))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.startswith("error:"))
        self.assertIn("missing.csv", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        r = run_cli(self.a.path, "export", str(self.tmp / "no" / "x.csv"))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.startswith("error:"))

    def test_store_json_valid_after_import(self):
        self.write_csv("id,title\n10,ten\n")
        run_cli(self.b.path, "import", str(self.csv))
        data = json.loads(self.b.path.read_text())
        self.assertEqual(data["next_id"], 11)
        r = run_cli(self.b.path, "add", "next")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.b.get(11)["title"], "next")

    def test_title_only_import_then_cli_add(self):
        for t in "abc":
            self.b.add(t)
        self.write_csv("title\nx\ny\nz\n")
        r = run_cli(self.b.path, "import", str(self.csv))
        self.assertEqual(r.stdout, "Imported 3 tasks, skipped 0 duplicates\n")
        run_cli(self.b.path, "add", "seventh")
        self.assertEqual(self.b.get(7)["title"], "seventh")

    def test_todo_file_env_still_works(self):
        self.a.add("env task")
        r = run_cli(self.a.path, "export", str(self.csv), use_env=True)
        self.assertEqual((r.returncode, r.stdout), (0, f"Exported 1 tasks to {self.csv}\n"))
        r = run_cli(self.b.path, "import", str(self.csv), use_env=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.b.list(), self.a.list())


if __name__ == "__main__":
    unittest.main()
