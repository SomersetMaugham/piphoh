"""S8 acceptance tests: `edit` CLI command (contract .harness/contracts/S8.md).

Each test name carries the Acceptance item number (test_aN_...).
All CLI calls run `python -m todo --file <tmp> ...` via subprocess from the repo root;
HOME points at a temp dir and TODO_FILE is removed, so ~/.todo.json is never touched.
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

NOTHING_MSG = "error: nothing to change (use --title, --due, --no-due or --priority)"


class S8Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-s8-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = self.tmp / "home"
        home.mkdir()
        env = {k: v for k, v in os.environ.items() if k != "TODO_FILE"}
        env["HOME"] = str(home)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env = env
        self.p = self.tmp / "t.json"

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "todo", "--file", str(self.p), *args],
            cwd=str(REPO_ROOT), capture_output=True, text=True, env=self.env, timeout=60,
        )

    def cli_ok(self, *args):
        r = self.cli(*args)
        self.assertEqual(r.returncode, 0, f"args={args} stdout={r.stdout!r} stderr={r.stderr!r}")
        self.assertNoTraceback(r)
        return r

    def assertNoTraceback(self, r):
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("Traceback", r.stdout)

    def tasks(self):
        r = self.cli_ok("list", "--json")
        return {t["id"]: t for t in json.loads(r.stdout)}

    def task1(self):
        return self.tasks()[1]

    def add_milk(self):
        r = self.cli_ok("add", "Buy milk")
        self.assertEqual(r.stdout, "Added task 1: Buy milk\n")

    def edit_item1(self):
        r = self.cli_ok("edit", "1", "--title", "Buy oat milk", "--due", "2026-12-01",
                        "--priority", "high")
        self.assertEqual(r.stdout, "Updated task 1: Buy oat milk\n")
        return r

    def bytes_(self):
        return self.p.read_bytes()


class TestA1EditAllFields(S8Base):
    def test_a1_edit_title_due_priority(self):
        self.add_milk()
        created = self.task1()["created"]
        self.edit_item1()
        t = self.task1()
        self.assertEqual(t["title"], "Buy oat milk")
        self.assertEqual(t["due"], "2026-12-01")
        self.assertEqual(t["priority"], "high")
        self.assertIs(t["done"], False)
        self.assertEqual(t["created"], created)
        self.assertEqual(sorted(self.tasks()), [1])


class TestA2PartialEdits(S8Base):
    def setUp(self):
        super().setUp()
        self.add_milk()
        self.edit_item1()

    def test_a2_no_due_clears_due_only(self):
        before = self.task1()
        r = self.cli_ok("edit", "1", "--no-due")
        self.assertEqual(r.stdout, "Updated task 1: Buy oat milk\n")
        t = self.task1()
        self.assertIsNone(t["due"])
        self.assertEqual(t["priority"], "high")
        self.assertEqual(t["title"], before["title"])
        self.assertEqual(t["created"], before["created"])
        self.assertEqual(t["done"], before["done"])

    def test_a2_priority_only(self):
        before = self.task1()
        r = self.cli_ok("edit", "1", "--priority", "low")
        self.assertEqual(r.stdout, "Updated task 1: Buy oat milk\n")
        after = self.task1()
        self.assertEqual(after["priority"], "low")
        before["priority"] = "low"
        self.assertEqual(after, before)

    def test_a2_title_is_trimmed(self):
        before = self.task1()
        r = self.cli_ok("edit", "1", "--title", "  Trimmed  ")
        self.assertEqual(r.stdout, "Updated task 1: Trimmed\n")
        after = self.task1()
        self.assertEqual(after["title"], "Trimmed")
        before["title"] = "Trimmed"
        self.assertEqual(after, before)


class TestA3NothingToChange(S8Base):
    def test_a3_no_options_is_error(self):
        self.add_milk()
        before = self.bytes_()
        r = self.cli("edit", "1")
        self.assertEqual(r.returncode, 1, r)
        self.assertEqual(r.stderr.strip(), NOTHING_MSG)
        self.assertEqual(r.stdout, "")
        self.assertNoTraceback(r)
        self.assertEqual(self.bytes_(), before)


class TestA4ValidationErrors(S8Base):
    def setUp(self):
        super().setUp()
        self.add_milk()
        self.before = self.bytes_()

    def check(self, *args, exact=None):
        r = self.cli("edit", "1", *args)
        self.assertEqual(r.returncode, 1, f"{args}: {r}")
        self.assertTrue(r.stderr.startswith("error:"), f"{args}: stderr={r.stderr!r}")
        self.assertNoTraceback(r)
        self.assertEqual(r.stdout, "")
        if exact is not None:
            self.assertEqual(r.stderr.strip(), exact)
        self.assertEqual(self.bytes_(), self.before, f"store changed by {args}")
        return r

    def test_a4_invalid_calendar_date(self):
        self.check("--due", "2026-02-30",
                   exact="error: due is not a valid calendar date: '2026-02-30'")

    def test_a4_bad_due_format(self):
        r = self.check("--due", "tomorrow")
        self.assertIn("due", r.stderr)

    def test_a4_blank_title(self):
        r = self.check("--title", "  ")
        self.assertIn("title", r.stderr)

    def test_a4_bad_due_with_other_fields_changes_nothing(self):
        self.check("--title", "New", "--priority", "low", "--due", "2026-02-30")


class TestA5ArgparseErrors(S8Base):
    def setUp(self):
        super().setUp()
        self.add_milk()
        self.before = self.bytes_()

    def check2(self, needle, *args):
        r = self.cli("edit", *args)
        self.assertEqual(r.returncode, 2, f"{args}: {r}")
        self.assertNoTraceback(r)
        # must be rejected by edit's own argparse rules, not because `edit` is unknown
        self.assertNotIn("invalid choice: 'edit'", r.stderr)
        self.assertIn(needle, r.stderr)
        self.assertEqual(self.bytes_(), self.before, f"store changed by {args}")

    def test_a5_due_and_no_due_mutually_exclusive(self):
        self.check2("not allowed with", "1", "--due", "2026-12-01", "--no-due")

    def test_a5_bad_priority_choice(self):
        self.check2("invalid choice: 'urgent'", "1", "--priority", "urgent")

    def test_a5_non_integer_id(self):
        self.check2("invalid int value", "abc", "--title", "x")


class TestA6UnknownId(S8Base):
    def test_a6_unknown_id(self):
        self.add_milk()
        before = self.bytes_()
        r = self.cli("edit", "42", "--title", "x")
        self.assertEqual(r.returncode, 1, r)
        self.assertEqual(r.stderr.strip(), "error: task 42 not found")
        self.assertEqual(r.stdout, "")
        self.assertNoTraceback(r)
        self.assertEqual(self.bytes_(), before)


class TestA7ListAfterEdit(S8Base):
    def test_a7_list_suffix_and_other_tasks_unchanged(self):
        self.add_milk()
        self.cli_ok("add", "Other", "--due", "2026-11-30", "--priority", "low")
        self.cli_ok("add", "Third")
        self.cli_ok("done", "3")
        others_before = {k: v for k, v in self.tasks().items() if k != 1}
        self.edit_item1()
        r = self.cli_ok("list")
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "1 [ ] Buy oat milk (due 2026-12-01, priority high)")
        self.assertEqual(lines[1], "2 [ ] Other (due 2026-11-30, priority low)")
        self.assertEqual(lines[2], "3 [x] Third")
        self.assertEqual(len(lines), 3)
        others_after = {k: v for k, v in self.tasks().items() if k != 1}
        self.assertEqual(others_after, others_before)

    def test_a7_no_due_list_line(self):
        self.add_milk()
        self.edit_item1()
        self.cli_ok("edit", "1", "--no-due")
        r = self.cli_ok("list")
        self.assertEqual(r.stdout.splitlines()[0], "1 [ ] Buy oat milk (priority high)")

    def test_a7_edit_keeps_done_flag(self):
        self.add_milk()
        self.cli_ok("done", "1")
        r = self.cli_ok("edit", "1", "--title", "Buy oat milk")
        self.assertEqual(r.stdout, "Updated task 1: Buy oat milk\n")
        self.assertIs(self.task1()["done"], True)
        self.assertEqual(self.cli_ok("list").stdout, "1 [x] Buy oat milk\n")


if __name__ == "__main__":
    unittest.main()
