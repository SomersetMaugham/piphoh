# QA report: S0 (walking skeleton)

Worktree: /home/claude/trial/todo-app/.harness/wt/qa-S0 (HEAD b880204, merge of harness/S0-tests into harness/S0). Python 3.13.18. PYTHONDONTWRITEBYTECODE=1 on all commands.

**Overall status: PASS** (9/9 acceptance items pass; preservation: none, first slice; regressions: none).

## Suites
- `python -m unittest discover -s tests -t .` -> Ran 15 tests, OK, exit 0
- `python -m unittest discover -s tests` -> Ran 15 tests, OK, exit 0
- Tracked-file hashes vs snapshot-qa-S0.json: 0 mismatches

## Acceptance items

### 1. `python -m todo --version` exits 0 and stdout (stripped) equals "todo " + todo.__version__.
- Status: **pass**
- Evidence:
  - python -m todo --version -> exit=0, stdout='todo 0.1.0\n' (cat -A: 'todo 0.1.0$'), stderr empty
  - acceptance test test_a1_version_output: ok
- Impact: None.
- Owner: developer
- Recommendation: Accept.

### 2. `todo.__version__` is a str matching ^\d+\.\d+\.\d+$.
- Status: **pass**
- Evidence:
  - python -c "import re,todo; ..." -> '0.1.0' str True
  - test_a2_version_is_str_semver: ok
- Impact: None.
- Owner: developer
- Recommendation: Accept.

### 3. `python -m todo` with no arguments exits 2, 'usage' on stderr, stdout empty.
- Status: **pass**
- Evidence:
  - python -m todo -> exit=2, stdout=[], stderr='usage: todo [-h] [--version] {} ...\ntodo: error: a command is required'
  - test_a3_no_args_usage_exit_2: ok
- Impact: None. Cosmetic: usage shows an empty '{}' choices placeholder until S2 registers a command.
- Owner: developer
- Recommendation: Accept.

### 4. `python -m todo --bogus` exits 2 with 'usage' on stderr.
- Status: **pass**
- Evidence:
  - python -m todo --bogus -> exit=2, stdout=[], stderr='usage: todo [-h] [--version] {} ...\ntodo: error: unrecognized arguments: --bogus'
  - test_a4_bogus_flag_usage_exit_2: ok
- Impact: None.
- Owner: developer
- Recommendation: Accept.

### 5. `main(["--version"])` raises SystemExit(0); main accepts argv and ignores sys.argv when given.
- Status: **pass**
- Evidence:
  - with sys.argv=['todo','--bogus-should-be-ignored']: main(['--version']) printed 'todo 0.1.0', SystemExit code=0; main([]) -> SystemExit code=2
  - COMMAND_MODULES == [] (list)
  - test_a5_main_accepts_argv_list, test_a5_command_modules_is_list: ok
- Impact: None.
- Owner: developer
- Recommendation: Accept.

### 6. `python -m unittest discover -s tests -t .` exits 0 and runs >= 1 test.
- Status: **pass**
- Evidence:
  - PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -t . -v -> 'Ran 15 tests ... OK', exit=0 (11 acceptance + 4 smoke)
- Impact: None.
- Owner: developer
- Recommendation: Accept.

### 7. `python -m unittest discover -s tests` (no -t) also exits 0.
- Status: **pass**
- Evidence:
  - PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v -> 'Ran 15 tests ... OK', exit=0
- Impact: None.
- Owner: developer
- Recommendation: Accept.

### 8. tests/__init__.py, tests/acceptance/__init__.py, todo/__init__.py, todo/__main__.py, todo/cli.py exist.
- Status: **pass**
- Evidence:
  - ls -l -> all five present (tests/*__init__.py 0 bytes; todo/__init__.py 55B; todo/__main__.py 56B; todo/cli.py 1068B)
  - todo/__main__.py content is exactly 'import sys; from todo.cli import main; sys.exit(main())'
- Impact: None.
- Owner: developer
- Recommendation: Accept.

### 9. No non-stdlib imports under todo/.
- Status: **pass**
- Evidence:
  - grep -rnE '^\s*(import|from)\s' todo/ -> sys, todo.cli, argparse, importlib, todo only
  - python -I import of todo, todo.cli succeeds; non-stdlib modules loaded: only todo, todo.cli (plus site's sitecustomize)
  - test_a9_no_non_stdlib_imports, test_a9_imports_resolve_in_isolated_python: ok
- Impact: None for the slice. Note: CLI type hints use `list[str] | None` (requires Python >= 3.10); tested on 3.13.18.
- Owner: developer
- Recommendation: Accept.

## Extra probes
- `python -m todo frob` -> exit 2, `invalid choice: 'frob' (choose from )`
- `python -m todo -h` -> exit 0, help on stdout

## Preservation
None (first slice).

## Regressions
None.

## Contract / harness issues
- QA-side test defect: tests/acceptance/s0/test_s0_acceptance.py::test_a9_imports_resolve_in_isolated_python runs `python -I -S`; -I implies -E, so PYTHONDONTWRITEBYTECODE is ignored and todo/__pycache__/*.pyc is created on every suite run (reproduced: rm -rf todo/__pycache__; run suite; dir reappears). Untracked and gitignored, so snapshot hashes are unaffected (verified 0 mismatches vs .harness/state/snapshot-qa-S0.json); QA removed the generated dir after runs. Recommend adding -B to that invocation in the S0 acceptance test.
- Contract does not state main()'s behaviour when no subcommand is parsed beyond the example (usage, exit 2); implementation uses parser.error('a command is required'), and also parser.error for a command lacking func. Consider making this explicit in the S2 contract so later slices keep it.
- Contract Interface requires Python 3.10+ implicitly (`list[str] | None` signature); minimum Python version is not stated.
