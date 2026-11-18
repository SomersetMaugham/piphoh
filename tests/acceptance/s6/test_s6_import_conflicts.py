"""S6 acceptance tests: CSV import conflict policy (contract .harness/contracts/S6.md).

Each test name carries the Acceptance item number (test_aN_...).
CLI runs use `python -B -m todo` as a subprocess with cwd = a temp dir and
PYTHONPATH = repo root. HOME points at a temp dir and TODO_FILE is stripped so
~/.todo.json is never touched.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

C1 = "2026-01-02T03:04:05Z"
C2 = "2026-02-03T04:05:06Z"


def renum(old, new):
    return f"Renumbered task {old} -> {new}: id {old} is used by a different task"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-s6-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = self.tmp / "home"
        home.mkdir()
        self.a = self.tmp / "a.json"
        self.s = self.tmp / "s.json"
        env = {k: v for k, v in os.environ.items() if k not in ("TODO_FILE", "PYTHONPATH")}
        env["HOME"] = str(home)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT)
        self.env = env
        from todo import TaskStore
        self.TaskStore = TaskStore

    def cli(self, store, *args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "todo", "--file", str(store), *args],
            cwd=str(self.tmp), capture_output=True, text=True, env=self.env, timeout=60,
        )

    def ok(self, store, *args):
        r = self.cli(store, *args)
        self.assertEqual(r.returncode, 0, f"args={args} stdout={r.stdout!r} stderr={r.stderr!r}")
        return r

    def assertLines(self, r, expected):
        self.assertEqual(r.stdout.splitlines(), expected, f"stderr={r.stderr!r}")

    def write_csv(self, name, text):
        p = self.tmp / name
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return p

    def titles(self, store):
        r = self.ok(store, "list", "--json")
        return {t["id"]: t["title"] for t in json.loads(r.stdout)}

    def seed(self, store, records):
        """Seed a store with exact ids/created via the library API."""
        self.TaskStore(store).restore(records)
        return Path(store).read_bytes()


class TestA1RenumberOnForeignId(Base):
    def test_a1_foreign_export_renumbered(self):
        self.TaskStore(self.s).add("existing one")
        sa = self.TaskStore(self.a)
        sa.add("Buy milk")
        sa.add("B")
        self.ok(self.a, "export", "out.csv")
        r = self.ok(self.s, "import", "out.csv")
        self.assertLines(r, ["Imported 2 tasks, skipped 0 duplicates", renum(1, 3)])
        self.assertEqual(self.titles(self.s), {1: "existing one", 2: "B", 3: "Buy milk"})


class TestA2OwnExportNoOp(Base):
    def test_a2_reimport_own_export_is_noop(self):
        sa = self.TaskStore(self.a)
        sa.add("A")
        sa.add("B")
        self.ok(self.a, "export", "out.csv")
        self.ok(self.s, "import", "out.csv")
        before = self.s.read_bytes()
        r = self.ok(self.s, "import", "out.csv")
        self.assertEqual(r.stdout, "Imported 0 tasks, skipped 2 duplicates\n")
        self.assertEqual(self.s.read_bytes(), before)


class TestA3SameTaskMutableStateIgnored(Base):
    def test_a3_same_id_created_title_skipped(self):
        before = self.seed(self.s, [{"id": 1, "title": "Task", "created": C1}])
        cases = [
            ("done", f"id,title,done,created\n1,Task,true,{C1}\n"),
            ("due", f"id,title,created,due\n1,Task,{C1},2027-01-01\n"),
            ("priority", f"id,title,created,priority\n1,Task,{C1},high\n"),
            ("all", f"id,title,done,created,due,priority\n1,Task,true,{C1},2027-01-01,low\n"),
            ("stripped title", f"id,title,created\n1,  Task  ,{C1}\n"),
        ]
        for name, text in cases:
            with self.subTest(case=name):
                self.write_csv("in.csv", text)
                r = self.ok(self.s, "import", "in.csv")
                self.assertLines(r, ["Imported 0 tasks, skipped 1 duplicates"])
                self.assertEqual(self.s.read_bytes(), before, "existing task changed")
                t = self.TaskStore(self.s).get(1)
                self.assertEqual((t["title"], t["done"], t["created"]), ("Task", False, C1))
                self.assertEqual((t["due"], t["priority"]), (None, "normal"))


class TestA4DifferentTaskRenumbered(Base):
    def test_a4_same_title_different_created(self):
        self.seed(self.s, [{"id": 1, "title": "Task", "created": C1}])
        self.write_csv("in.csv", f"id,title,created\n1,Task,{C2}\n")
        r = self.ok(self.s, "import", "in.csv")
        self.assertLines(r, ["Imported 1 tasks, skipped 0 duplicates", renum(1, 2)])
        st = self.TaskStore(self.s)
        self.assertEqual(st.get(1)["created"], C1)
        self.assertEqual((st.get(2)["title"], st.get(2)["created"]), ("Task", C2))

    def test_a4_no_created_column(self):
        self.seed(self.s, [{"id": 1, "title": "Task", "created": C1}])
        self.write_csv("in.csv", "id,title\n1,Task\n")
        r = self.ok(self.s, "import", "in.csv")
        self.assertLines(r, ["Imported 1 tasks, skipped 0 duplicates", renum(1, 2)])
        self.assertEqual(self.titles(self.s), {1: "Task", 2: "Task"})
        self.assertEqual(self.TaskStore(self.s).get(1)["created"], C1)

    def test_a4_blank_created_cell(self):
        # Interface: explicit `created` means a non-blank cell.
        self.seed(self.s, [{"id": 1, "title": "Task", "created": C1}])
        self.write_csv("in.csv", "id,title,created\n1,Task,\n")
        r = self.ok(self.s, "import", "in.csv")
        self.assertLines(r, ["Imported 1 tasks, skipped 0 duplicates", renum(1, 2)])

    def test_a4_same_created_different_title(self):
        self.seed(self.s, [{"id": 1, "title": "Task", "created": C1}])
        self.write_csv("in.csv", f"id,title,created\n1,Other,{C1}\n")
        r = self.ok(self.s, "import", "in.csv")
        self.assertLines(r, ["Imported 1 tasks, skipped 0 duplicates", renum(1, 2)])
        self.assertEqual(self.titles(self.s), {1: "Task", 2: "Other"})


class TestA5InFileRepeat(Base):
    def test_a5_repeat_id_renumbered(self):
        self.write_csv("dup.csv", "id,title\n5,First\n5,Second\n")
        r = self.ok(self.s, "import", "dup.csv")
        self.assertLines(r, ["Imported 2 tasks, skipped 0 duplicates", renum(5, 6)])
        self.assertEqual(self.titles(self.s), {5: "First", 6: "Second"})

    def test_a5_identical_rows_second_skipped(self):
        self.write_csv("dup.csv", f"id,title,created\n5,First,{C1}\n5,First,{C1}\n")
        r = self.ok(self.s, "import", "dup.csv")
        self.assertLines(r, ["Imported 1 tasks, skipped 1 duplicates"])
        self.assertEqual(self.titles(self.s), {5: "First"})


class TestA6IdAssignmentOrder(Base):
    def test_a6_renumbered_blank_and_explicit_mix(self):
        st = self.TaskStore(self.s)
        st.add("one")
        st.add("two")  # ids 1,2; next_id 3
        self.write_csv("mix.csv", "id,title\n1,X\n,Y\n10,Z\n")
        r = self.ok(self.s, "import", "mix.csv")
        self.assertLines(r, ["Imported 3 tasks, skipped 0 duplicates", renum(1, 11)])
        self.assertEqual(self.titles(self.s), {1: "one", 2: "two", 10: "Z", 11: "X", 12: "Y"})
        r = self.ok(self.s, "add", "Next")
        self.assertEqual(r.stdout.strip(), "Added task 13: Next")

    def test_a6_renumber_never_reuses_deleted_id(self):
        # Interface: fresh id assigned like a blank-id record (S1: ids never reused).
        st = self.TaskStore(self.s)
        st.add("one")
        st.add("two")
        st.add("three")
        st.delete(3)  # next_id stays 4
        self.write_csv("in.csv", "id,title\n1,X\n")
        r = self.ok(self.s, "import", "in.csv")
        self.assertLines(r, ["Imported 1 tasks, skipped 0 duplicates", renum(1, 4)])


class TestA7RestoreReturn(Base):
    def test_a7_restore_in_file_repeat(self):
        st = self.TaskStore(self.s)
        res = st.restore([{"id": 5, "title": "First"}, {"id": 5, "title": "Second"}])
        self.assertEqual(res, {"imported": [5, 6], "skipped": [], "renumbered": [[5, 6]]})

    def test_a7_restore_empty(self):
        res = self.TaskStore(self.s).restore([])
        self.assertEqual(res, {"imported": [], "skipped": [], "renumbered": []})

    def test_a7_restore_collision_with_store(self):
        st = self.TaskStore(self.s)
        st.add("Original")
        res = st.restore([{"id": 1, "title": "Replacement", "done": True},
                          {"id": 2, "title": "New", "done": False}])
        # imported = final ids in record order (Replacement -> 3, New -> 2)
        self.assertEqual(res, {"imported": [3, 2], "skipped": [], "renumbered": [[1, 3]]})
        t1, t2, t3 = st.get(1), st.get(2), st.get(3)
        self.assertEqual((t1["title"], t1["done"]), ("Original", False))
        self.assertEqual(t2["title"], "New")
        self.assertEqual((t3["title"], t3["done"]), ("Replacement", True))

    def test_a7_restore_same_task_skipped(self):
        st = self.TaskStore(self.s)
        st.restore([{"id": 1, "title": "Task", "created": C1}])
        res = st.restore([{"id": 1, "title": "Task", "created": C1, "done": True}])
        self.assertEqual(res, {"imported": [], "skipped": [1], "renumbered": []})
        self.assertIs(st.get(1)["done"], False)


class TestA8ImportCsvInProcess(Base):
    def test_a8_import_csv_fresh_store(self):
        from todo.csvio import export_csv, import_csv
        sa = self.TaskStore(self.a)
        sa.add("One")
        sa.add("Two")
        p = self.tmp / "p.csv"
        export_csv(sa, p)
        res = import_csv(self.TaskStore(self.s), p)
        self.assertEqual(res, {"imported": 2, "skipped": 0, "renumbered": []})

    def test_a8_import_csv_reports_renumbered(self):
        from todo.csvio import import_csv
        self.TaskStore(self.s).add("Original")
        p = self.write_csv("in.csv", "id,title,done\n1,Replacement,true\n2,New,false\n")
        res = import_csv(self.TaskStore(self.s), p)
        self.assertEqual(res, {"imported": 2, "skipped": 0, "renumbered": [[1, 3]]})


class TestA9AllOrNothing(Base):
    def test_a9_invalid_row_after_colliding_row(self):
        self.TaskStore(self.s).add("Original")
        before = self.s.read_bytes()
        self.write_csv("in.csv", "id,title,done\n1,Replacement,true\n2,Bad,maybe\n")
        r = self.cli(self.s, "import", "in.csv")
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout!r} stderr={r.stderr!r}")
        self.assertTrue(r.stderr.startswith("error: in.csv:3:"), r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.s.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
