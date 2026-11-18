# Handoff
QA-owned test location: tests/acceptance/<slice id lowercased>/ (e.g. tests/acceptance/s1/)
Test command: python -m unittest discover -s tests -t .
## Verified behaviors (Preservation list)
- (none yet)
## Open gaps / regressions
- (none)
## Decisions
- stdlib only; unittest; package name `todo`
- Store: `todo.store.TaskStore(path=None)`; path precedence explicit > env TODO_FILE > ~/.todo.json; errors in `todo.errors` (TodoError, TaskNotFound, ValidationError, StoreError). Task = dict {id,title,done,created}; tests compare by key subset (S3 adds due/priority).
- Field extension points: `TaskStore.CREATE_FIELDS` / `UPDATE_FIELDS`; REST uses them, S3 extends them.
- CLI: `todo.cli.COMMAND_MODULES` registry, each module has `register(subparsers)`; global `--file`; TodoError -> stderr `error: <msg>`, exit 1; usage errors exit 2. `list --json` for machine-readable output.
- REST: `todo.server.make_server(store, host, port=0)`; DELETE returns 204; 405 for wrong method.
- S3: tasks always carry `due` (str|None) + `priority` (low|normal|high, default normal); legacy tasks backfilled on read. CREATE_FIELDS=(title,due,priority), UPDATE_FIELDS=(title,done,due,priority). `list(*, status=None, sort=None)`; final tie-break = id asc; due sort puts no-due last; priority order high>normal>low.
- S3 CLI list suffix only for non-default values: ` (due D)`, ` (priority P)`, ` (due D, priority P)`; default lines identical to S2. `add` stdout unchanged.
- Shared create-path validator `TaskStore._validate_create(title, fields) -> dict` (used by add, S5 restore); first of S3/S5 to land creates it.
- S5: module `todo.csvio` (COMMAND_MODULES += "todo.csvio"); fixed CSV header `id,title,done,created,due,priority`; import via `TaskStore.restore(records)` all-or-nothing on invalid rows; duplicate ids (in store or file) skipped, never overwritten; blank id -> new id; next_id bumped past imported ids.
## Contract changes
- (none)
- Verified (S0): `python -m todo --version` -> "todo 0.1.0" exit 0; no args / bad flag -> usage on stderr, exit 2; both discovery forms green (evidence/S0/qa_report.md)
## Open items from QA (for Planner)
- S0 test a9 uses `python -I -S` which ignores PYTHONDONTWRITEBYTECODE -> add -B (QA-owned test fix)
- State in S2 contract: main() with no command -> argparse error "a command is required", exit 2
- Minimum Python version unstated; code uses `X | None` hints (3.10+). Decide and record.
- (Orchestrator) Minimum Python: 3.10+ (code uses `X | None`). Import may restore a deleted task's id (accepted).
- (Orchestrator) plan.json: S3 now depends on S1+S2 (needs todo/commands.py); S3 and S5 share area "store" (both edit store.py) so they build one after another.
- Verified (S1): TaskStore add/list/get/complete/update/delete, ids never reused, TODO_FILE/arg path precedence, errors TaskNotFound/ValidationError/StoreError (evidence/S1/qa_report.md)
- Verified (S2): CLI add/list/list --json/done/rm, --file > TODO_FILE, error: <msg> exit 1, usage exit 2 (evidence/S2/qa_report.md)
- Verified (S4): REST GET/POST /tasks, GET/PATCH/DELETE /tasks/<id>; 201+Location, 204, 400 JSON, 404, 405+Allow; 20 concurrent POSTs -> ids 1..20 (evidence/S4/qa_report.md)
- Verified (S5, pre-S3 parts): CSV export/import round-trip, all-or-nothing import, duplicate ids skipped, next_id bump, BOM/non-ASCII (evidence/S5/qa_report.md). S3-dependent S5 items (3, 7 due/priority) must be re-verified with S3.
- Verified (S3): due/priority validation, list --status/--sort, list suffixes, REST fields; S5 follow-up items 3 and 7 pass (evidence/S3/qa_report.md)
## Decisions (planning pass S6-S8, 2026-11-18)
- S6 "same task" rule for CSV import: record with explicit id N is the same task as task N iff it has an explicit `created` equal to the task's AND the stripped title is equal; done/due/priority ignored. Same -> skipped ("duplicate"); different task on a taken id (store or earlier file row) -> renumbered to a fresh id (assigned like blank-id rows, after explicit ids, file order). Never overwrite.
- S6 interface: `TaskStore.restore` -> `{"imported": [ids], "skipped": [ids], "renumbered": [[old, new], ...]}`; `csvio.import_csv` -> `{"imported": n, "skipped": m, "renumbered": [[old, new], ...]}`. CLI import line 1 unchanged; then one line per renumbered row: `Renumbered task <old> -> <new>: id <old> is used by a different task`.
- S7: `serve --port` validated by argparse type (0..65535) -> usage error exit 2 `argument --port: port must be an integer from 0 to 65535, got '<v>'`. Store load rejects tasks with missing/invalid `created`, invalid present `due`/`priority`, duplicate ids (StoreError `invalid store file <path>: ...`); missing due/priority keys stay legal. `cli.main` last resort: other Exception -> `error: unexpected <Type>: <msg>` exit 1; KeyboardInterrupt -> 130. `_resolve_path` expands `~` (arg and TODO_FILE). `--file` added centrally by `cli.build_parser` to every subparser (default SUPPRESS) after registration; later occurrence wins. Argparse usage errors keep `<prog>: error: <msg>` format.
- S8: `edit <id> [--title T] [--due D | --no-due] [--priority P]` in todo/commands.py; stdout `Updated task <id>: <title>`; no options -> `error: nothing to change (use --title, --due, --no-due or --priority)` exit 1. README examples starting `python -m todo ` in fenced blocks must run (except serve).
- Areas: S6 and S7 both edit todo/store.py -> both area "store" (S6 first). S8 area "commands" (commands.py, README.md only; must not edit cli.py). S7 edits cli.py, server.py, store.py; S6 edits store.py, csvio.py.
## Contract changes (from S6)
- S5 acceptance item 4 second half changes: CSV with id 5 twice (different titles) now imports both (5 and 6, second renumbered) instead of skipping the second; a row colliding with a different existing task (test_a4_existing_task_never_overwritten) is now imported under a new id (existing task still never overwritten). S5 item 11 / restore results gain key `renumbered`. QA updates tests/acceptance/s5; Dev updates tests/test_csvio.py. S5 item 4 first half (own re-export is a no-op) is unchanged.
## Open items (for Orchestrator/user)
- README (S8) does not yet describe S6 renumbering or S7 `--file`-after-subcommand / `~`; a small doc touch-up after S6/S7 merge is needed (could be folded into whichever of S6/S7 lands last, but that would add README.md to area "store").
- (Orchestrator) Open questions from S6–S8 planning: bad --port uses argparse usage error, exit 2 (accepted); malformed store records are rejected strictly with a clear error (accepted); README moves out of S8 into new slice S9 (pm_ok, deps S6+S7+S8) so it documents final behavior.
- (Coordinator decisions) README moved from S8 to S9 (area "docs", deps S6+S7+S8); bad --port = argparse usage error exit 2 accepted; strict rejection of malformed store records accepted. S8 now = `edit` only, deps S2+S3. README must document S6 renumbering, S7 `--file` anywhere and `~`, S8 `edit`; its fenced `python -m todo ` lines (non-serve) must run.
- Verified (S6): id collision with a different task -> renumbered, never dropped; own-export re-import is a no-op; all-or-nothing on bad rows (evidence/S6/qa_report.md)
## Open items (round 2)
- QA S6: matching "same task" only against the task holding the same id means importing the same foreign file twice duplicates renumbered rows, and identical repeated rows both import. Candidate follow-up: treat a row as the same task if ANY existing task has the same created+title.
- Verified (S8): edit --title/--due/--no-due/--priority, nothing-to-change error, store unchanged on errors (evidence/S8/qa_report.md)
- Verified (S7): no tracebacks for bad --port / malformed store (CLI exit 1 one error line; REST 500 JSON), ~ expansion, --file after subcommand (evidence/S7/qa_report.md)
- Verified (S9): README examples all run; outputs match; REST/CSV/edit/--file/~ documented (evidence/S9/qa_report.md)
