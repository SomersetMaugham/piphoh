# S7 QA report: error hardening

**Overall: PASS.** All 7 Acceptance items and all Preservation checks pass. No regressions. Both original independent-QA tracebacks (serve --port 99999, and export with a task missing `created`) are gone.

Worktree `.harness/wt/qa-S7` (detached at harness/S7, 2e11fed). Nothing was edited there and the tree stayed clean with no pycache. Runs used temp HOME, temp stores and temp cwd, with TODO_FILE unset and PYTHONDONTWRITEBYTECODE=1. Every server started was stopped with SIGINT (rc 0), and no background jobs were left running.

## Suite
- `discover -s tests -t .`: 235 tests, OK (skipped=1)
- `discover -s tests`: 235 tests, OK (skipped=1)
- s7 acceptance: 20/20 OK. The one skip is the pre-S3-only S5 test and is expected.

## Acceptance
- **PASS** 1. serve --port 99999 / -1 -> exit 2 'error: argument --port: port must be an integer from 0 to 65535', no Traceback; --port abc exit 2
  - Original independent-QA traceback re-run: 'serve --port 99999' -> rc 2, stderr last line "todo serve: error: argument --port: port must be an integer from 0 to 65535, got '99999'", no Traceback
  - Same rc 2 and message, no traceback, for '-1', 'abc', '65536', '1.5', '' and '0x50'; parser accepts 0 and 65535
- **PASS** 2. Store task lacking created / due 5 / priority 'urgent' / duplicate id 1: list, list --json, add Z, done 1, export o.csv -> exit 1, one exact stderr line, bytes unchanged, o.csv absent
  - All 4 malformed stores x 7 commands (list, list --json, add Z, done 1, rm 1, export o.csv, import in.csv): rc 1, stdout empty, stderr exactly 'error: invalid store file <path>: <why>\n' with why = task 1 has invalid 'created'/'due'/'priority' or 'duplicate task id 1'; store bytes unchanged; o.csv never created
  - Original independent-QA traceback re-run: export with task missing created -> rc 1, "error: invalid store file <path>: task 1 has invalid 'created'", no Traceback, o.csv absent
  - Extra: created 'yesterday' rejected the same way; due null + priority high accepted
- **PASS** 3. REST against item-2 stores: GET /tasks -> 500 JSON {'error': ...}, server keeps running
  - CLI 'serve --port 0' on each of the 4 stores: GET /tasks, GET /tasks/1, GET /tasks again, POST /tasks -> all 500 with {'error': 'invalid store file <path>: <why>'}; process still alive after; SIGINT -> rc 0, no Traceback; store bytes unchanged
- **PASS** 4. Legacy task without due/priority keys still lists
  - list -> '1 [ ] old'; list --json -> due None, priority 'normal'; file bytes unchanged after reads
- **PASS** 5. In-process: TaskStore.list raises RuntimeError('boom') -> cli.main(['list']) == 1, stderr 'error: unexpected RuntimeError: boom'
  - rc 1, stderr 'error: unexpected RuntimeError: boom\n'
  - Extra: KeyboardInterrupt -> rc 130, no stdout or stderr output
- **PASS** 6. ~ expansion with temp HOME: TaskStore('~/a.json').path; TODO_FILE='~/b.json'; --file '~/c.json'; no ~ dir in cwd
  - TaskStore('~/a.json').path == HOME/a.json True; TODO_FILE ~/b.json -> HOME/b.json created; --file ~/c.json add -> HOME/c.json; add D --file ~/d.json -> HOME/d.json; cwd stays empty (no '~' dir)
- **PASS** 7. --file after subcommand for add/list/done/rm/export/import behaves identically; parse_args(['serve','--file','X']).file == 'X'; --file A list --file B reads B; no --file -> None
  - Identical command sequence (add T, add U, list, done 1, list --json, rm 1, export, import, list, rm 9) run with --file before vs after: same rc/stdout/stderr (created timestamps normalised) and same final store contents
  - build_parser(): serve --file X -> 'X'; list -> None; --file A list --file B -> 'B'; CLI '--file A list --file B' lists 'from B'; after-subcommand --file beats TODO_FILE
  - serve --port 0 --file X (after subcommand) served the X store in the REST smoke

## Preservation
- **PASS** Full suite, both discovery forms (S0-S7 acceptance + dev tests): discover -s tests -t . : Ran 235, OK (skipped=1); discover -s tests : Ran 235, OK (skipped=1); s7 acceptance 20/20 OK; the one skip is the expected pre-S3-only S5 test
- **PASS** S0 --version / no command -> usage exit 2: --version rc 0 'todo 0.1.0'; no command rc 2
- **PASS** S2 output lines, error: exit 1, --file > TODO_FILE: 'Added task N: ...', list lines unchanged; done 42 -> rc 1 'error: task 42 not found'; --file A with TODO_FILE=B lists A
- **PASS** S4 port 0, 'port in use' message, SIGINT exit 0, REST shape: serve --port 0 prints 'Serving on http://127.0.0.1:<port>'; busy port -> rc 1 'error: cannot listen on 127.0.0.1:<p>: Address already in use'; SIGINT rc 0 no traceback; REST smoke: GET 200, POST 201, PATCH 200, GET /tasks/99 404, POST with color 400, DELETE 204
- **PASS** S5 CSV errors: missing import file -> rc 1 'error: cannot read <path>: ...'; S5/S6 suites green
- **PASS** S3 legacy backfill: acceptance item 4
- **PASS** S1 StoreError for bad JSON / structure: '{nope' -> rc 1 'error: invalid JSON in <path>: ...'; tasks:{} -> rc 1 "error: invalid store file <path>: 'tasks' must be a list"

## Contract issues (non-blocking)
- Non-blocking, owner planner: --port parses with int(), so '8_0', ' 80 ', '+80' and non-ASCII digits such as '٨٠' are accepted as port 80. These are harmless and within the contract's 'integers 0..65535', but a stricter rule would need a contract change.
