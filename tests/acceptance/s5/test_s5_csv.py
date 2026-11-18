"""S5 acceptance tests: CSV export/import (contract .harness/contracts/s5.md).

Each test name carries the Acceptance item number (test_aN_...).
CLI runs use `python -B -m todo` as a subprocess with cwd = a temp dir (so the
CSV path can be given relative, as in the contract's stdout examples) and
PYTHONPATH = repo root. HOME points at a temp dir and TODO_FILE is stripped so
~/.todo.json is never touched.

Items that need S3 (due/priority) skip with a clear reason when the store does
not list 'priority'/'due' in TaskStore.CREATE_FIELDS.
"""
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

HEADER = "id,title,done,created,due,priority"
CREATED_RE = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"


def _store_cls():
    from todo import TaskStore
    return TaskStore


def has_s3():
    try:
        fields = _store_cls().CREATE_FIELDS
    except Exception:  # noqa: BLE001 - store missing => treat as pre-S3
        return False
    return "priority" in fields and "due" in fields


S3_SKIP = "requires S3 (due/priority not in TaskStore.CREATE_FIELDS yet)"


class CsvTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-s5-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = self.tmp / "home"
        home.mkdir()
        self.a = self.tmp / "a.json"
        self.b = self.tmp / "b.json"
        env = {k: v for k, v in os.environ.items() if k not in ("TODO_FILE", "PYTHONPATH")}
        env["HOME"] = str(home)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT)
        self.env = env
        self.TaskStore = _store_cls()

    # -- helpers ---------------------------------------------------------
    def cli(self, store, *args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "todo", "--file", str(store), *args],
            cwd=str(self.tmp), capture_output=True, text=True, env=self.env, timeout=60,
        )

    def ok(self, store, *args):
        r = self.cli(store, *args)
        self.assertEqual(r.returncode, 0, f"args={args} stdout={r.stdout!r} stderr={r.stderr!r}")
        return r

    def assertCliError(self, r, contains=None):
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout!r} stderr={r.stderr!r}")
        self.assertTrue(r.stderr.startswith("error:"), r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        if contains is not None:
            self.assertIn(contains, r.stderr)

    def write_csv(self, name, text, encoding="utf-8"):
        p = self.tmp / name
        with open(p, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
        return p

    def read_rows(self, name):
        with open(self.tmp / name, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def store_bytes(self, path):
        return Path(path).read_bytes() if Path(path).exists() else None

    def assertRecentCreated(self, created):
        self.assertRegex(created, CREATED_RE)
        ts = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertLessEqual(abs(time.time() - ts.timestamp()), 5, created)


class TestA1RoundTripCli(CsvTestBase):
    def test_a1_export_import_round_trip(self):
        sa = self.TaskStore(self.a)
        sa.add("Buy milk")
        sa.add('Say "hi", world\nsecond line')
        sa.complete(2)
        r = self.ok(self.a, "export", "out.csv")
        self.assertEqual(r.stdout.strip(), "Exported 2 tasks to out.csv")
        r = self.ok(self.b, "import", "out.csv")
        self.assertEqual(r.stdout.strip(), "Imported 2 tasks, skipped 0 duplicates")
        self.assertEqual(self.TaskStore(self.b).list(), self.TaskStore(self.a).list())


class TestA2ExportFormat(CsvTestBase):
    def test_a2_header_and_done_strings(self):
        sa = self.TaskStore(self.a)
        sa.add("Open one")
        sa.add("Done one")
        sa.complete(2)
        self.ok(self.a, "export", "out.csv")
        raw = (self.tmp / "out.csv").read_bytes()
        self.assertTrue(raw.startswith((HEADER + "\r\n").encode()), raw[:80])
        rows = self.read_rows("out.csv")
        self.assertEqual([r["id"] for r in rows], ["1", "2"])
        self.assertEqual([r["done"] for r in rows], ["false", "true"])
        for r in rows:
            self.assertEqual(r["due"], "")
            self.assertEqual(r["priority"], "normal" if has_s3() else "")
            self.assertEqual(r["created"], sa.get(int(r["id"]))["created"])

    def test_a2_empty_store_header_only(self):
        r = self.ok(self.a, "export", "out.csv")
        self.assertEqual(r.stdout.strip(), "Exported 0 tasks to out.csv")
        text = (self.tmp / "out.csv").read_text(encoding="utf-8")
        self.assertEqual(text.splitlines(), [HEADER])


@unittest.skipUnless(has_s3(), S3_SKIP)
class TestA3S3RoundTrip(CsvTestBase):
    def test_a3_due_priority_round_trip(self):
        sa = self.TaskStore(self.a)
        sa.add("Pay rent", due="2026-12-01", priority="high")
        sa.add("Low only", priority="low")
        sa.add("Due only", due="2027-01-15")
        sa.add("Neither")
        sa.complete(1)
        self.ok(self.a, "export", "out.csv")
        self.ok(self.b, "import", "out.csv")
        self.assertEqual(self.TaskStore(self.b).list(), self.TaskStore(self.a).list())
        rows = {r["id"]: r for r in self.read_rows("out.csv")}
        self.assertEqual((rows["1"]["due"], rows["1"]["priority"]), ("2026-12-01", "high"))
        self.assertEqual((rows["4"]["due"], rows["4"]["priority"]), ("", "normal"))


class TestA4Duplicates(CsvTestBase):
    def test_a4_reimport_skips_all(self):
        sa = self.TaskStore(self.a)
        sa.add("A")
        sa.add("B")
        self.ok(self.a, "export", "out.csv")
        self.ok(self.b, "import", "out.csv")
        before = self.TaskStore(self.b).list()
        r = self.ok(self.b, "import", "out.csv")
        self.assertEqual(r.stdout.strip(), "Imported 0 tasks, skipped 2 duplicates")
        self.assertEqual(self.TaskStore(self.b).list(), before)

    def test_a4_same_id_twice_in_file(self):
        # S6 contract change: a repeated id with a different task is renumbered, not skipped.
        self.write_csv("dup.csv", "id,title\n5,First\n5,Second\n")
        r = self.ok(self.b, "import", "dup.csv")
        self.assertEqual(r.stdout.splitlines(), [
            "Imported 2 tasks, skipped 0 duplicates",
            "Renumbered task 5 -> 6: id 5 is used by a different task",
        ])
        tasks = self.TaskStore(self.b).list()
        self.assertEqual([(t["id"], t["title"]) for t in tasks], [(5, "First"), (6, "Second")])

    def test_a4_existing_task_never_overwritten(self):
        sb = self.TaskStore(self.b)
        sb.add("Original")
        self.write_csv("in.csv", "id,title,done\n1,Replacement,true\n2,New,false\n")
        r = self.ok(self.b, "import", "in.csv")
        # S6 contract change: the colliding row is imported under a fresh id (3), not skipped.
        self.assertEqual(r.stdout.splitlines(), [
            "Imported 2 tasks, skipped 0 duplicates",
            "Renumbered task 1 -> 3: id 1 is used by a different task",
        ])
        t1 = self.TaskStore(self.b).get(1)
        self.assertEqual((t1["title"], t1["done"]), ("Original", False))
        self.assertEqual(self.TaskStore(self.b).get(2)["title"], "New")
        t3 = self.TaskStore(self.b).get(3)
        self.assertEqual((t3["title"], t3["done"]), ("Replacement", True))


class TestA5TitleOnly(CsvTestBase):
    def test_a5_title_only_gets_new_ids(self):
        sb = self.TaskStore(self.b)
        for t in ("x1", "x2", "x3"):
            sb.add(t)  # next_id is now 4
        self.write_csv("titles.csv", "title\nAlpha\nBeta\nGamma\n")
        r = self.ok(self.b, "import", "titles.csv")
        self.assertEqual(r.stdout.strip(), "Imported 3 tasks, skipped 0 duplicates")
        new = [t for t in self.TaskStore(self.b).list() if t["id"] >= 4]
        self.assertEqual([t["id"] for t in new], [4, 5, 6])
        self.assertEqual([t["title"] for t in new], ["Alpha", "Beta", "Gamma"])
        for t in new:
            self.assertIs(t["done"], False)
            self.assertRecentCreated(t["created"])
        r = self.ok(self.b, "add", "Next")
        self.assertEqual(r.stdout.strip(), "Added task 7: Next")


class TestA6NextIdBump(CsvTestBase):
    def test_a6_imported_id_bumps_next_id(self):
        self.write_csv("ten.csv", "id,title\n10,Ten\n")
        self.ok(self.b, "import", "ten.csv")
        self.assertEqual(self.TaskStore(self.b).get(10)["title"], "Ten")
        r = self.ok(self.b, "add", "After")
        self.assertEqual(r.stdout.strip(), "Added task 11: After")


class TestA7InvalidRows(CsvTestBase):
    HEAD = "id,title,done,created,due,priority\n"
    VALID = "7,Valid row,false,2026-11-18T14:20:05Z,,\n"   # line 2
    CASES = [
        ("done=maybe", "8,Bad,maybe,2026-11-18T14:20:05Z,,\n"),
        ("id=abc", "abc,Bad,false,2026-11-18T14:20:05Z,,\n"),
        ("id=0", "0,Bad,false,2026-11-18T14:20:05Z,,\n"),
        ("created=yesterday", "8,Bad,false,yesterday,,\n"),
        ("blank title", "8,,false,2026-11-18T14:20:05Z,,\n"),
    ]

    def _check_rejected(self, name, bad_row):
        sb = self.TaskStore(self.b)
        if not self.b.exists():
            sb.add("Existing")
        before = self.store_bytes(self.b)
        p = self.write_csv("in.csv", self.HEAD + self.VALID + bad_row)  # bad row = line 3
        r = self.cli(self.b, "import", "in.csv")
        self.assertCliError(r, contains=":3:")
        self.assertEqual(self.store_bytes(self.b), before, "store file changed")
        self.assertEqual(r.stdout, "")

    def test_a7_invalid_rows_rejected_all_or_nothing(self):
        for name, row in self.CASES:
            with self.subTest(case=name):
                self._check_rejected(name, row)

    @unittest.skipUnless(has_s3(), S3_SKIP)
    def test_a7_s3_invalid_due_rejected(self):
        self._check_rejected("due=2026-02-30", "8,Bad,false,2026-11-18T14:20:05Z,2026-02-30,\n")

    @unittest.skipUnless(has_s3(), S3_SKIP)
    def test_a7_s3_invalid_priority_rejected(self):
        # Interface: non-empty priority goes through S3 validation.
        self._check_rejected("priority=urgent", "8,Bad,false,2026-11-18T14:20:05Z,,urgent\n")

    @unittest.skipIf(has_s3(), "pre-S3 behaviour only (S3 is merged)")
    def test_a7_pre_s3_nonempty_due_rejected(self):
        # Interface: pre-S3 stores reject non-empty due/priority as unknown fields.
        self._check_rejected("due pre-S3", "8,Bad,false,2026-11-18T14:20:05Z,2026-12-01,\n")


class TestA8BadFiles(CsvTestBase):
    def _check(self, csv_text):
        self.TaskStore(self.b).add("Existing")
        before = self.store_bytes(self.b)
        self.write_csv("in.csv", csv_text)
        r = self.cli(self.b, "import", "in.csv")
        self.assertCliError(r)
        self.assertEqual(self.store_bytes(self.b), before)

    def test_a8_header_without_title(self):
        self._check("id,done\n1,true\n")

    def test_a8_unknown_column(self):
        self._check("title,color\nA,red\n")

    def test_a8_empty_file(self):
        self._check("")

    def test_a8_missing_file_error_has_path(self):
        r = self.cli(self.b, "import", "does-not-exist.csv")
        self.assertCliError(r, contains="does-not-exist.csv")
        self.assertFalse(self.b.exists(), "import of missing file created the store")


class TestA9ExportPaths(CsvTestBase):
    def test_a9_export_overwrites(self):
        self.TaskStore(self.a).add("Only")
        (self.tmp / "out.csv").write_text("junk\n" * 50, encoding="utf-8")
        r = self.ok(self.a, "export", "out.csv")
        self.assertEqual(r.stdout.strip(), "Exported 1 tasks to out.csv")
        text = (self.tmp / "out.csv").read_text(encoding="utf-8")
        self.assertNotIn("junk", text)
        lines = text.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], HEADER)

    def test_a9_export_to_missing_dir(self):
        self.TaskStore(self.a).add("Only")
        r = self.cli(self.a, "export", str(Path("no-such-dir") / "out.csv"))
        self.assertCliError(r)
        self.assertFalse((self.tmp / "no-such-dir").exists())


class TestA10Encoding(CsvTestBase):
    def test_a10_bom_csv_imports(self):
        self.write_csv("bom.csv", "title,done\nCafé,true\n", encoding="utf-8-sig")
        self.assertTrue((self.tmp / "bom.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
        r = self.ok(self.b, "import", "bom.csv")
        self.assertEqual(r.stdout.strip(), "Imported 1 tasks, skipped 0 duplicates")
        tasks = self.TaskStore(self.b).list()
        self.assertEqual(len(tasks), 1)
        self.assertEqual((tasks[0]["title"], tasks[0]["done"]), ("Café", True))

    def test_a10_non_ascii_round_trip(self):
        sa = self.TaskStore(self.a)
        for t in ("Café crème", "日本語のタスク", "Ünïcödé ✓ 🚀"):
            sa.add(t)
        self.ok(self.a, "export", "out.csv")
        raw = (self.tmp / "out.csv").read_bytes()
        self.assertIn("日本語のタスク".encode("utf-8"), raw)
        self.ok(self.b, "import", "out.csv")
        self.assertEqual(self.TaskStore(self.b).list(), self.TaskStore(self.a).list())


class TestA11InProcess(CsvTestBase):
    def test_a11_export_import_functions(self):
        from todo.csvio import export_csv, import_csv
        s1 = self.TaskStore(self.a)
        s1.add("One")
        s1.add("Two")
        p = self.tmp / "p.csv"
        self.assertEqual(export_csv(s1, p), 2)
        s2 = self.TaskStore(self.b)
        # S6 contract change: result gains key "renumbered".
        self.assertEqual(import_csv(s2, p), {"imported": 2, "skipped": 0, "renumbered": []})
        self.assertEqual(s2.list(), s1.list())

    def test_a11_columns_constant(self):
        from todo import csvio
        self.assertEqual(tuple(csvio.COLUMNS), tuple(HEADER.split(",")))


if __name__ == "__main__":
    unittest.main()
