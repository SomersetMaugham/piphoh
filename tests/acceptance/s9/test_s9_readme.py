"""S9 acceptance tests: README.md (contract .harness/contracts/S9.md).

Each test name carries the Acceptance item number (test_aN_...).
Item 1 runs every runnable README example (`python -m todo ...` lines in fenced
blocks other than ```text, excluding `serve`) as `sys.executable -B -m todo ...`
with cwd = a fresh temp dir, HOME = temp, TODO_FILE = <temp>/store.json,
PYTHONPATH = repo root and PYTHONDONTWRITEBYTECODE=1. ~/.todo.json is never touched.
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "README.md"

SECTIONS = ["Requirements", "Quick start", "Store file", "CLI commands", "REST API",
            "CSV export/import", "Running tests"]
SUBCOMMANDS = ["add", "list", "done", "rm", "edit", "export", "import", "serve"]
OPTIONS = ["--due", "--priority", "--status", "--sort", "--json", "--title", "--no-due",
           "--port", "--version", "--file"]
MUST_RUN = ["add", "list", "done", "edit", "rm", "export", "import"]
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+-]*)")
BASE_REF = os.environ.get("S9_BASE_REF", "harness/integration")


def read_readme(test):
    if not README.is_file():
        test.fail(f"{README} does not exist")
    return README.read_text(encoding="utf-8")


def code_blocks(text):
    """Yield (info, [lines]) for each fenced code block."""
    fence = None
    info = ""
    lines = []
    for line in text.splitlines():
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence, info, lines = m.group(1), m.group(2).lower(), []
        elif m and line.strip().startswith(fence[0] * len(fence)) and not m.group(2):
            yield info, lines
            fence = None
        else:
            lines.append(line)


def prose_lines(text):
    """Lines outside fenced code blocks."""
    out, fence = [], None
    for line in text.splitlines():
        m = FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(1)
        elif fence is not None and m and not m.group(2) and line.strip().startswith(fence):
            fence = None
        elif fence is None:
            out.append(line)
    return out


def runnable_examples(text):
    """Logical `python -m todo ...` lines from non-text fenced blocks, in document order."""
    out = []
    for info, lines in code_blocks(text):
        if info == "text":
            continue
        joined, buf = [], ""
        for line in lines:  # join backslash continuations
            if line.rstrip().endswith("\\"):
                buf += line.rstrip()[:-1] + " "
                continue
            joined.append(buf + line)
            buf = ""
        if buf:
            joined.append(buf)
        for line in joined:
            s = line.strip()
            if not s.startswith("python -m todo "):
                continue
            argv = shlex.split(s, comments=True)[3:]
            if "serve" in argv:
                continue
            out.append((s, argv))
    return out


def section(text, name):
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^##\s+{re.escape(name)}\s*$", line):
            start = i + 1
            break
    if start is None:
        return None
    body = []
    for line in lines[start:]:
        if re.match(r"^##\s", line):
            break
        body.append(line)
    return "\n".join(body)


class TestA1ExecutableExamples(unittest.TestCase):
    def test_a1_examples_run_in_order(self):
        text = read_readme(self)
        examples = runnable_examples(text)
        seen = set()
        # The subcommand is the first non-option token (an example may lead with --file X).
        for _, argv in examples:
            rest = list(argv)
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] == "--file" else rest[1:]
            if rest:
                seen.add(rest[0])
        missing = [c for c in MUST_RUN if c not in seen]
        self.assertEqual(missing, [], f"no runnable example for: {missing}")

        tmp = Path(tempfile.mkdtemp(prefix="todo-s9-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        home = tmp / "home"
        home.mkdir()
        work = tmp / "work"
        work.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ("TODO_FILE", "PYTHONPATH")}
        env.update(HOME=str(home), TODO_FILE=str(tmp / "store.json"),
                   PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
        for line, argv in examples:
            with self.subTest(example=line):
                r = subprocess.run([sys.executable, "-B", "-m", "todo", *argv], cwd=str(work),
                                   capture_output=True, text=True, env=env, timeout=60)
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(r.returncode, 0,
                                 f"{line!r}: rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}")

    def test_a1_parser_self_check(self):
        # Guards the example extractor itself (no README needed).
        sample = (
            "```sh\npython -m todo add \"Buy milk\" --due 2026-12-01  # comment\n"
            "python -m todo serve --port 8000\n$ python -m todo rm 9\n```\n"
            "```text\npython -m todo done 99\n```\n"
            "```\npython -m todo list \\\n  --json\n```\n"
        )
        self.assertEqual(runnable_examples(sample), [
            ('python -m todo add "Buy milk" --due 2026-12-01  # comment',
             ["add", "Buy milk", "--due", "2026-12-01"]),
            ("python -m todo list    --json", ["list", "--json"]),
        ])


class TestA2Headings(unittest.TestCase):
    def test_a2_required_sections_in_order(self):
        text = read_readme(self)
        heads = [m.group(1).strip() for line in prose_lines(text)
                 if (m := re.match(r"^##\s+(.+?)\s*#*\s*$", line))]
        missing = [s for s in SECTIONS if s not in heads]
        self.assertEqual(missing, [], f"missing ## sections; found {heads}")
        order = [h for h in heads if h in SECTIONS]
        self.assertEqual(order, SECTIONS, f"## sections out of order: {heads}")


class TestA3Basics(unittest.TestCase):
    def test_a3_required_strings(self):
        text = read_readme(self)
        for s in ("python -m todo", "3.10", "TODO_FILE", "~/.todo.json"):
            with self.subTest(s=s):
                self.assertIn(s, text)

    def test_a3_file_after_subcommand_example(self):
        text = read_readme(self)
        self.assertRegex(text, r"python -m todo \w+ .*--file ")


class TestA4CliReference(unittest.TestCase):
    def test_a4_subcommands_and_options(self):
        text = read_readme(self)
        for sub in SUBCOMMANDS:
            with self.subTest(subcommand=sub):
                self.assertRegex(text, rf"(?<![\w-]){re.escape(sub)}(?![\w-])")
        for opt in OPTIONS:
            with self.subTest(option=opt):
                self.assertRegex(text, rf"(?<![\w-]){re.escape(opt)}(?![\w-])")


class TestA5Rest(unittest.TestCase):
    def test_a5_rest_section(self):
        text = read_readme(self)
        body = section(text, "REST API")
        self.assertIsNotNone(body, "no '## REST API' section")
        for s in ("GET /tasks", "POST /tasks", "GET /tasks/<id>", "PATCH /tasks/<id>",
                  "DELETE /tasks/<id>"):
            with self.subTest(endpoint=s):
                self.assertIn(s, body)
        for code in ("201", "204", "400", "404"):
            with self.subTest(code=code):
                self.assertRegex(body, rf"\b{code}\b")


class TestA6Csv(unittest.TestCase):
    def test_a6_csv_section(self):
        text = read_readme(self)
        body = section(text, "CSV export/import")
        self.assertIsNotNone(body, "no '## CSV export/import' section")
        for s in ("id,title,done,created,due,priority", "Renumbered", "duplicates"):
            with self.subTest(s=s):
                self.assertIn(s, body)


class TestA7TestCommand(unittest.TestCase):
    def test_a7_test_command(self):
        self.assertIn("python -m unittest discover -s tests", read_readme(self))


class TestA8OnlyReadme(unittest.TestCase):
    """Slice touches only README.md (QA's own tests/acceptance/s9/ are allowed)."""

    @staticmethod
    def _allowed(path):
        return path == "README.md" or path.startswith("tests/acceptance/s9/")

    def _git(self, *args):
        r = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True,
                           timeout=60)
        if r.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {r.stderr.strip()}")
        return r.stdout

    def test_a8_no_source_or_test_changes(self):
        if shutil.which("git") is None:
            self.skipTest("git not available")
        if subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "-q", BASE_REF],
                          capture_output=True).returncode != 0:
            self.skipTest(f"base ref {BASE_REF!r} not found (set S9_BASE_REF)")
        base = self._git("merge-base", "HEAD", BASE_REF).strip()
        changed = set(self._git("diff", "--name-only", base).split())  # commits + working tree
        changed |= set(self._git("ls-files", "--others", "--exclude-standard").split())
        bad = sorted(p for p in changed if not self._allowed(p))
        self.assertEqual(bad, [], f"files other than README.md changed vs {BASE_REF}")


if __name__ == "__main__":
    unittest.main()
