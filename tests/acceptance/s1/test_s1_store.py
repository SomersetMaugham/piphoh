"""S1 acceptance tests: JSON store library API (contract .harness/contracts/s1.md).

Each test name carries the Acceptance item number (test_aN_...).
All stores use temp paths; HOME is redirected to a temp dir and TODO_FILE is
removed for every test so ~/.todo.json is never touched.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BASE_KEYS = {"id", "title", "done", "created"}
CREATED_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


class StoreTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="todo-s1-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = {k: v for k, v in os.environ.items() if k != "TODO_FILE"}
        env["HOME"] = str(self.home)
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from todo.store import TaskStore  # noqa: F401  (fails until S1 exists)
        from todo import errors  # noqa: F401
        self.TaskStore = TaskStore
        self.errors = errors
        self.p = self.tmp / "t.json"

    def store(self, path=None):
        return self.TaskStore(self.p if path is None else path)

    def ids(self, tasks):
        return [t["id"] for t in tasks]


class TestS1Store(StoreTestBase):
    def test_a1_add_persists_and_new_instance_lists(self):
        self.store().add("Buy milk")
        tasks = self.TaskStore(self.p).list()
        self.assertEqual(len(tasks), 1)
        t = tasks[0]
        self.assertEqual(t["id"], 1)
        self.assertEqual(t["title"], "Buy milk")
        self.assertIs(t["done"], False)
        with open(self.p, encoding="utf-8") as fh:
            json.load(fh)  # valid JSON

    def test_a2_add_return_shape_and_created(self):
        before = datetime.now(timezone.utc)
        t = self.store().add("x")
        after = datetime.now(timezone.utc)
        self.assertIsInstance(t, dict)
        self.assertTrue(BASE_KEYS <= set(t), f"missing keys: {BASE_KEYS - set(t)}")
        self.assertIs(type(t["id"]), int)
        self.assertIsInstance(t["title"], str)
        self.assertIs(type(t["done"]), bool)
        self.assertIsInstance(t["created"], str)
        self.assertRegex(t["created"], CREATED_RE)
        created = datetime.strptime(t["created"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertLessEqual(abs((created - before).total_seconds()), 5)
        self.assertLessEqual(abs((after - created).total_seconds()), 5)

    def test_a3_title_stripped(self):
        self.assertEqual(self.store().add("  x  ")["title"], "x")

    def test_a3_invalid_titles_raise_validation_error(self):
        s = self.store()
        for bad in ("", "   ", None, 5):
            with self.subTest(title=bad):
                with self.assertRaises(self.errors.ValidationError) as cm:
                    s.add(bad)
                self.assertIsInstance(cm.exception, self.errors.TodoError)
                self.assertIsInstance(cm.exception, ValueError)
        self.assertEqual(s.list(), [])

    def test_a3_unknown_field_raises_validation_error(self):
        s = self.store()
        with self.assertRaises(self.errors.ValidationError):
            s.add("x", bogus=1)
        self.assertEqual(s.list(), [])

    def test_a4_list_missing_file_empty_and_not_created(self):
        p = self.tmp / "nope.json"
        self.assertEqual(self.store(p).list(), [])
        self.assertFalse(p.exists())

    def test_a4_ids_in_order_after_three_adds(self):
        s = self.store()
        for title in ("a", "b", "c"):
            s.add(title)
        self.assertEqual(self.ids(s.list()), [1, 2, 3])
        self.assertEqual(self.ids(self.store().list()), [1, 2, 3])

    def test_a5_complete_idempotent_and_persisted(self):
        s = self.store()
        s.add("a")
        self.assertIs(s.complete(1)["done"], True)
        again = s.complete(1)
        self.assertIs(again["done"], True)
        self.assertEqual(again["id"], 1)
        self.assertIs(self.store().get(1)["done"], True)

    def test_a6_delete_returns_task_then_gone(self):
        s = self.store()
        for title in ("a", "b", "c"):
            s.add(title)
        deleted = s.delete(2)
        self.assertEqual(deleted["id"], 2)
        self.assertEqual(deleted["title"], "b")
        with self.assertRaises(self.errors.TaskNotFound) as cm:
            s.get(2)
        self.assertEqual(cm.exception.task_id, 2)
        self.assertEqual(self.ids(s.list()), [1, 3])
        self.assertEqual(self.ids(self.store().list()), [1, 3])

    def test_a7_ids_never_reused(self):
        s = self.store()
        self.assertEqual(s.add("A")["id"], 1)
        self.assertEqual(s.add("B")["id"], 2)
        s.delete(2)
        self.assertEqual(s.add("C")["id"], 3)
        # also across a fresh instance
        self.store().delete(3)
        self.assertEqual(self.store().add("D")["id"], 4)

    def test_a8_unknown_id_raises_task_not_found(self):
        s = self.store()
        s.add("a")
        calls = {
            "get": lambda: s.get(99),
            "complete": lambda: s.complete(99),
            "delete": lambda: s.delete(99),
            "update": lambda: s.update(99, title="z"),
        }
        for name, call in calls.items():
            with self.subTest(method=name):
                with self.assertRaises(self.errors.TaskNotFound) as cm:
                    call()
                self.assertIsInstance(cm.exception, self.errors.TodoError)
                self.assertEqual(cm.exception.task_id, 99)
                self.assertEqual(str(cm.exception), "task 99 not found")
        self.assertEqual(self.ids(s.list()), [1])

    def test_a9_update_title_and_done_persist(self):
        s = self.store()
        s.add("Old")
        s.complete(1)
        r = s.update(1, title="New")
        self.assertEqual(r["title"], "New")
        self.assertEqual(self.store().get(1)["title"], "New")
        r = s.update(1, done=False)
        self.assertIs(r["done"], False)
        got = self.store().get(1)
        self.assertIs(got["done"], False)
        self.assertEqual(got["title"], "New")

    def test_a9_update_invalid_raises_validation_error(self):
        s = self.store()
        s.add("Keep")
        cases = {
            "no fields": {},
            "done=1": {"done": 1},
            "title empty": {"title": ""},
            "unknown key": {"color": "red"},
        }
        for label, kwargs in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(self.errors.ValidationError):
                    s.update(1, **kwargs)
        t = self.store().get(1)
        self.assertEqual(t["title"], "Keep")
        self.assertIs(t["done"], False)

    def test_a10_returned_dict_is_a_copy(self):
        s = self.store()
        t = s.add("orig")
        t["title"] = "hack"
        self.assertEqual(s.get(t["id"])["title"], "orig")
        g = s.get(t["id"])
        g["title"] = "hack2"
        lst = s.list()
        lst[0]["title"] = "hack3"
        self.assertEqual(s.get(t["id"])["title"], "orig")

    def test_a11_path_from_env(self):
        envp = self.tmp / "env.json"
        with mock.patch.dict(os.environ, {"TODO_FILE": str(envp)}):
            s = self.TaskStore()
        self.assertIsInstance(s.path, Path)
        self.assertEqual(s.path, Path(str(envp)))

    def test_a11_explicit_path_beats_env(self):
        envp = self.tmp / "env.json"
        argp = self.tmp / "arg.json"
        with mock.patch.dict(os.environ, {"TODO_FILE": str(envp)}):
            s = self.TaskStore(argp)
            s2 = self.TaskStore(str(argp))
        self.assertEqual(s.path, argp)
        self.assertEqual(s2.path, argp)

    def test_a11_default_is_home_todo_json(self):
        self.assertNotIn("TODO_FILE", os.environ)
        s = self.TaskStore()
        self.assertEqual(s.path, Path(str(self.home)) / ".todo.json")

    def test_a12_invalid_json_raises_store_error_with_path(self):
        self.p.write_text("{not json", encoding="utf-8")
        with self.assertRaises(self.errors.StoreError) as cm:
            self.store().list()
        self.assertIsInstance(cm.exception, self.errors.TodoError)
        self.assertIn(str(self.p), str(cm.exception))

    def test_a13_parent_dir_created_on_first_write(self):
        p = self.tmp / "sub" / "dir" / "t.json"
        self.assertFalse(p.parent.exists())
        self.store(p).add("a")
        self.assertTrue(p.is_file())
        with open(p, encoding="utf-8") as fh:
            json.load(fh)
        self.assertEqual(self.ids(self.store(p).list()), [1])

    def test_a14_public_reexports(self):
        import todo
        from todo import TaskStore, TodoError, TaskNotFound, ValidationError, StoreError
        self.assertIs(TaskStore, self.TaskStore)
        self.assertTrue(issubclass(TaskNotFound, TodoError))
        self.assertTrue(issubclass(ValidationError, TodoError))
        self.assertTrue(issubclass(ValidationError, ValueError))
        self.assertTrue(issubclass(StoreError, TodoError))
        self.assertTrue(issubclass(TodoError, Exception))
        self.assertIs(todo.TaskNotFound, self.errors.TaskNotFound)


if __name__ == "__main__":
    unittest.main()
