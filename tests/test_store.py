import json
import os
import re
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from todo import StoreError, TaskNotFound, TaskStore, TodoError, ValidationError


class StoreTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.path = self.tmp / "t.json"
        self.store = TaskStore(self.path)

    def tearDown(self):
        self._tmp.cleanup()


class AddListTest(StoreTestBase):
    def test_add_returns_record(self):
        t = self.store.add("  Buy milk ")
        self.assertEqual((t["id"], t["title"], t["done"]), (1, "Buy milk", False))
        self.assertRegex(t["created"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        created = datetime.strptime(t["created"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertLess(abs((datetime.now(timezone.utc) - created).total_seconds()), 5)

    def test_add_persists_and_file_format(self):
        self.store.add("a")
        data = json.loads(self.path.read_text())
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["next_id"], 2)
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(TaskStore(self.path).list()[0]["title"], "a")

    def test_add_invalid(self):
        for bad in ("", "   ", None, 5, b"x"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.store.add(bad)
        with self.assertRaises(ValidationError):
            self.store.add("x", bogus=1)
        self.assertFalse(self.path.exists())

    def test_validation_error_hierarchy(self):
        self.assertTrue(issubclass(ValidationError, TodoError))
        self.assertTrue(issubclass(ValidationError, ValueError))

    def test_list_missing_file(self):
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.path.exists())

    def test_list_sorted_ids(self):
        for title in "abc":
            self.store.add(title)
        self.assertEqual([t["id"] for t in self.store.list()], [1, 2, 3])

    def test_ids_not_reused(self):
        self.store.add("A")
        self.store.add("B")
        self.store.delete(2)
        self.assertEqual(self.store.add("C")["id"], 3)

    def test_copies_are_independent(self):
        t = self.store.add("x")
        t["title"] = "hack"
        self.store.list()[0]["title"] = "hack2"
        self.assertEqual(self.store.get(1)["title"], "x")

    def test_parent_dir_created(self):
        p = self.tmp / "sub" / "dir" / "t.json"
        TaskStore(p).add("x")
        self.assertTrue(p.is_file())

    def test_no_temp_files_left(self):
        self.store.add("x")
        self.store.complete(1)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["t.json"])

    def test_concurrent_adds_in_one_instance(self):
        threads = [threading.Thread(target=self.store.add, args=(f"t{i}",)) for i in range(20)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual([t["id"] for t in self.store.list()], list(range(1, 21)))


class MutateTest(StoreTestBase):
    def setUp(self):
        super().setUp()
        for title in ("one", "two", "three"):
            self.store.add(title)

    def test_complete_idempotent_and_persisted(self):
        self.assertTrue(self.store.complete(1)["done"])
        self.assertTrue(self.store.complete(1)["done"])
        self.assertTrue(TaskStore(self.path).get(1)["done"])

    def test_delete(self):
        self.assertEqual(self.store.delete(2)["id"], 2)
        with self.assertRaises(TaskNotFound) as cm:
            self.store.get(2)
        self.assertEqual(cm.exception.task_id, 2)
        self.assertEqual([t["id"] for t in self.store.list()], [1, 3])

    def test_unknown_id(self):
        for call in (self.store.get, self.store.complete, self.store.delete,
                     lambda i: self.store.update(i, title="x")):
            with self.subTest(call=call), self.assertRaises(TaskNotFound) as cm:
                call(99)
            self.assertEqual(cm.exception.task_id, 99)
            self.assertEqual(str(cm.exception), "task 99 not found")

    def test_update_persists(self):
        self.store.update(1, title="  New ")
        self.store.complete(1)
        self.store.update(1, done=False)
        t = TaskStore(self.path).get(1)
        self.assertEqual((t["title"], t["done"]), ("New", False))

    def test_update_invalid(self):
        cases = [{}, {"done": 1}, {"done": "true"}, {"title": ""}, {"title": None},
                 {"color": "red"}, {"id": 5}, {"created": "x"}]
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.store.update(1, **fields)
        self.assertEqual(self.store.get(1)["title"], "one")

    def test_update_validates_before_lookup(self):
        with self.assertRaises(ValidationError):
            self.store.update(99, color="red")

    def test_separate_instances_see_writes(self):
        other = TaskStore(self.path)
        other.delete(3)
        self.assertEqual(len(self.store.list()), 2)


class PathResolutionTest(unittest.TestCase):
    def test_precedence(self):
        with tempfile.TemporaryDirectory() as d:
            env_path = os.path.join(d, "env.json")
            with mock.patch.dict(os.environ, {"TODO_FILE": env_path}):
                self.assertEqual(TaskStore().path, Path(env_path))
                self.assertEqual(TaskStore(Path(d) / "x.json").path, Path(d) / "x.json")
                self.assertEqual(TaskStore(os.path.join(d, "s.json")).path, Path(d) / "s.json")
            env = {k: v for k, v in os.environ.items() if k != "TODO_FILE"}
            env["HOME"] = d
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(TaskStore().path, Path(d) / ".todo.json")

    def test_path_is_pathlib(self):
        self.assertIsInstance(TaskStore("x.json").path, Path)


class CorruptFileTest(StoreTestBase):
    def assertStoreError(self, content):
        self.path.write_text(content)
        with self.assertRaises(StoreError) as cm:
            self.store.list()
        self.assertIn(str(self.path), str(cm.exception))
        self.assertIsInstance(cm.exception, TodoError)

    def test_invalid_json(self):
        self.assertStoreError("{not json")

    def test_wrong_structure(self):
        for content in ("[]", '{"tasks": []}', '{"next_id": 1, "tasks": {}}',
                        '{"next_id": 1, "tasks": [1]}',
                        '{"next_id": 1, "tasks": [{"id": 1, "title": "a", "done": false}]}'):
            with self.subTest(content=content):
                self.assertStoreError(content)

    def test_corrupt_file_not_overwritten_on_add(self):
        self.path.write_text("{bad")
        with self.assertRaises(StoreError):
            self.store.add("x")
        self.assertEqual(self.path.read_text(), "{bad")


if __name__ == "__main__":
    unittest.main()
