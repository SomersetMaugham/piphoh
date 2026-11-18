"""Acceptance tests for slice S0 (walking skeleton).

Each test name carries the contract's Acceptance item number (a1..a9).
All behaviour is observed via subprocesses using sys.executable, run from the
repo root. Stdlib only; no imports through the ``tests.`` prefix.
"""
import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Guard against infinite recursion: A6/A7 run unittest discovery over tests/,
# which re-discovers this module. The nested run sets this env var and the
# discovery tests skip themselves there.
NESTED_ENV = "HARNESS_S0_NESTED_DISCOVERY"


def _env(**extra):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(extra)
    return env


def run_py(*args, timeout=60, env=None):
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env or _env(),
    )


def run_cli(*args):
    return run_py("-m", "todo", *args)


def get_version():
    r = run_py("-c", "import todo; print(todo.__version__)")
    if r.returncode != 0:
        raise AssertionError("cannot import todo: " + r.stderr)
    return r.stdout.strip()


class TestA1VersionOutput(unittest.TestCase):
    def test_a1_version_output(self):
        version = get_version()
        r = run_cli("--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "todo " + version)


class TestA2VersionFormat(unittest.TestCase):
    def test_a2_version_is_str_semver(self):
        r = run_py("-c", "import todo; print(type(todo.__version__).__name__); print(todo.__version__)")
        self.assertEqual(r.returncode, 0, r.stderr)
        type_name, version = r.stdout.splitlines()[:2]
        self.assertEqual(type_name, "str")
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")


class TestA3NoArgs(unittest.TestCase):
    def test_a3_no_args_usage_exit_2(self):
        r = run_cli()
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage", r.stderr.lower())
        self.assertEqual(r.stdout, "")


class TestA4BogusFlag(unittest.TestCase):
    def test_a4_bogus_flag_usage_exit_2(self):
        r = run_cli("--bogus")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage", r.stderr.lower())


class TestA5MainArgv(unittest.TestCase):
    def test_a5_main_accepts_argv_list(self):
        # sys.argv is deliberately set to something that would fail (exit 2)
        # if main() read it instead of the list passed in.
        code = (
            "import sys\n"
            "sys.argv = ['todo', '--bogus-from-sys-argv']\n"
            "from todo.cli import main\n"
            "try:\n"
            "    main(['--version'])\n"
            "except SystemExit as e:\n"
            "    print('EXIT', e.code)\n"
            "else:\n"
            "    print('NOEXIT')\n"
        )
        r = run_py("-c", code)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertIn(lines[-1] if lines else "", ("EXIT 0", "EXIT None"),
                      "main(['--version']) must raise SystemExit(0); got:\n" + r.stdout + r.stderr)
        self.assertIn("todo " + get_version(), r.stdout)

    def test_a5_command_modules_is_list(self):
        r = run_py("-c", "import todo.cli as c; print(isinstance(c.COMMAND_MODULES, list))")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "True")


@unittest.skipIf(os.environ.get(NESTED_ENV), "nested discovery run")
class TestA6A7Discovery(unittest.TestCase):
    def _discover(self, *extra):
        return run_py("-m", "unittest", "discover", "-s", "tests", *extra,
                      timeout=600, env=_env(**{NESTED_ENV: "1"}))

    def _ran(self, r):
        m = re.search(r"^Ran (\d+) tests?", r.stderr, re.M)
        self.assertIsNotNone(m, "no 'Ran N tests' line:\n" + r.stderr[-2000:])
        return int(m.group(1))

    def test_a6_discover_with_top_level(self):
        r = self._discover("-t", ".")
        self.assertEqual(r.returncode, 0, r.stderr[-4000:])
        self.assertGreaterEqual(self._ran(r), 1)

    def test_a7_discover_without_top_level(self):
        r = self._discover()
        self.assertEqual(r.returncode, 0, r.stderr[-4000:])
        self.assertGreaterEqual(self._ran(r), 1)


class TestA8Files(unittest.TestCase):
    def test_a8_required_files_exist(self):
        for rel in ("tests/__init__.py", "tests/acceptance/__init__.py",
                    "todo/__init__.py", "todo/__main__.py", "todo/cli.py"):
            with self.subTest(path=rel):
                self.assertTrue((REPO_ROOT / rel).is_file(), rel + " missing")


class TestA9StdlibOnly(unittest.TestCase):
    def test_a9_no_non_stdlib_imports(self):
        pkg = REPO_ROOT / "todo"
        files = sorted(pkg.rglob("*.py"))
        self.assertTrue(files, "no .py files under todo/")
        stdlib = set(sys.stdlib_module_names) | set(sys.builtin_module_names)
        bad = []
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import within package
                        continue
                    names = [node.module or ""]
                for n in names:
                    top = n.split(".")[0]
                    if top != "todo" and top not in stdlib and top != "__future__":
                        bad.append(f"{f.relative_to(REPO_ROOT)}: {n}")
        self.assertEqual(bad, [], "non-stdlib imports found")

    def test_a9_imports_resolve_in_isolated_python(self):
        # -I ignores user site-packages and PYTHONPATH; -S skips site-packages.
        r = run_py("-I", "-S", "-B", "-c",
                   "import sys; sys.path.insert(0, '.'); import todo, todo.cli; print('ok')")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
