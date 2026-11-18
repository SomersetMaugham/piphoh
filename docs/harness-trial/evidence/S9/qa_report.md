# S9 QA report: README

**Overall: PASS.** All 8 Acceptance items and all Preservation checks pass. No regressions. One non-blocking prose inaccuracy is noted below: the bad-JSON error message.

Worktree `.harness/wt/qa-S9` (detached at harness/S9, ecdfdcb). Nothing was edited there and the tree stayed clean. Runs used temp HOME, temp cwd and temp stores, with PYTHONDONTWRITEBYTECODE=1. The server was stopped with SIGINT (rc 0), and no background jobs or servers were left running.

## Suite
- `discover -s tests -t .`: 267 tests, OK (skipped=1)
- `discover -s tests`: 267 tests, OK (skipped=1)

## Acceptance
- **PASS** 1. Every fenced 'python -m todo ' line (non-serve) runs in order in a fresh temp cwd with PYTHONPATH=repo, HOME=temp, TODO_FILE=<temp>/store.json -> exit 0, no Traceback; covers add/list/done/edit/rm/export/import
  - All 17 lines rc 0, no Traceback: --version; add x2; list; done 1; list --status open --sort due; --file work.json add; list --file work.json; --file ~/todo-work.json list; edit 2 --title/--priority; edit 2 --no-due; list --json; add Temporary; rm 3; export tasks.csv; import tasks.csv; --file work.json import tasks.csv
  - Ids are consistent: Temporary is task 3 and rm 3 deletes it; export writes tasks.csv before it is imported
  - Also ran '--file ~/todo-work.json list' with a literal, unexpanded '~' (S7 expansion): rc 0 'No tasks.'
- **PASS** 2. Seven ## headings in order
  - Requirements, Quick start, Store file, CLI commands, REST API, CSV export/import, Running tests are present in this order; s9 test_a2 ok
- **PASS** 3. python -m todo, 3.10, TODO_FILE, ~/.todo.json, --file after subcommand example
  - All present; 'python -m todo list --file work.json' matches the regex and ran rc 0
- **PASS** 4. Every subcommand/option incl. --no-due
  - add --due/--priority, list --status/--sort/--json, done, rm, edit --title/--due/--no-due/--priority, export, import, serve --port, --version all appear in the CLI table; exit codes 0/1/2 documented and verified (done 42 -> 1, edit 1 -> 1, serve --port 99999 -> 2, done with no id -> 2)
- **PASS** 5. REST endpoints and codes 201/204/400/404
  - All 5 endpoints and the codes are in the table. Manual serve + the README's curl commands, run exactly as written (plain -d, no Content-Type): GET 200 [], POST 201 with Location: /tasks/1 and the documented task shape, PATCH 200 done true, DELETE 204 no body; also GET /tasks/1 after delete -> 404, PUT /tasks -> 405 'Allow: GET, POST', blank title -> 400 {'error': ...}; defaults port 8000 / host 127.0.0.1 confirmed via parser; SIGINT rc 0
- **PASS** 6. CSV header, Renumbered, duplicates
  - Header text 'id,title,done,created,due,priority' matches the real export's first line; the documented outputs 'Imported 0 tasks, skipped 2 duplicates' and 'Imported 2 tasks, skipped 0 duplicates' + 'Renumbered task 1 -> 3: id 1 is used by a different task' match the real output byte-for-byte; blank id/done/created/priority defaults and all-or-nothing on an invalid row ('error: blank.csv:3: ...', nothing created) verified
- **PASS** 7. Test command present
  - 'python -m unittest discover -s tests' is present and runs green (below)
- **PASS** 8. Slice touches only README.md
  - Dev commit 87f0984: README.md only (151 insertions). Other changes on the slice are QA's tests/acceptance/s9 only

## Preservation
- **PASS** Whole suite green, both discovery forms: discover -s tests -t . : Ran 267, OK (skipped=1); discover -s tests : Ran 267, OK (skipped=1); s9 acceptance 10/10 OK; the only skip is the expected pre-S3-only S5 test
- **PASS** Previously verified CLI/REST/CSV behaviour unchanged (no code changes): no source changes in slice; CLI, REST and CSV runs above match the S2-S8 behaviour

## Findings (non-blocking)
- Non-blocking README inaccuracy, owner developer: the Store file section says that for an invalid store, 'bad JSON' included, 'every command stops with `error: invalid store file <path>: <reason>`'. In reality bad JSON prints 'error: invalid JSON in <path>: <reason>' (S1 message); only structural problems use 'invalid store file'. Also `serve` does not stop: it starts and answers each request with 500 {'error': ...} (S7 item 3). Suggested fix: 'commands fail with `error: invalid JSON in <path>: ...` or `error: invalid store file <path>: <reason>` (the REST server answers 500)'. No numbered Acceptance item covers this prose, so the overall status stays pass.
- Cosmetic: the Quick start text block shows `list` output as it looks after `done 1`, while the sh block's first `list` comes before `done 1`. The prose makes this understandable.
