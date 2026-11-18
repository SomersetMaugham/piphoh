# QA report: S4 (REST API)

**Status: PASS.** Worktree wt/qa-S4 @ 6b830a2 (harness/S4). Every command run with PYTHONDONTWRITEBYTECODE=1 (inline scripts with -B); temp HOME and store files; servers stopped afterwards (no `serve` processes left).

## Test runs
- `python -m unittest discover -s tests -t .`: Ran 105 tests, OK (s0 11, s1 20, s2 14, s4 19, plus developer tests)
- `python -m unittest discover -s tests`: Ran 105 tests, OK
- `git diff --stat harness/S4-tests harness/S4 -- tests/acceptance/s4`: empty
- testguard: OK with 1 stale file (see Notes)

## Acceptance
| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | POST {title:'Buy milk'} -> 201 id 1/done false; GET /tasks -> [task 1] | pass | live server (python -m todo --file <tmp> serve --port <free>), /tmp/qa-s1-scripts/s4live.py: 201 {id:1,title:'Buy milk',done:false,created:...}; GET /tasks 200 [task 1]; test_s4 a1 ok |
| 2 | POST has Location /tasks/1 and Content-Type application/json | pass | live: Location '/tasks/1', Content-Type 'application/json'; suite ok |
| 3 | GET /tasks empty -> 200 [] | pass | live: 200 []; suite ok |
| 4 | GET /tasks/1 200; /tasks/99 404 'not found'; /tasks/abc 404 | pass | live: 200 task; 404 {'error':'task 99 not found'}; 404 {'error':'not found'}; /tasks/ (trailing slash) 200; suite ok |
| 5 | PATCH done true / title New -> 200, persisted | pass | live: both 200; TaskStore(tmp).get(1) -> title 'New', done True; suite ok |
| 6 | PATCH invalid bodies -> 400 JSON error; PATCH /tasks/99 -> 404 | pass | live: {done:'yes'} 400 'done must be a boolean'; {color} 400 'unknown field(s): color'; {} 400 'no fields to update'; 'not json' 400 'request body must be valid JSON'; /tasks/99 404; suite ok |
| 7 | POST invalid bodies -> 400 JSON error; store unchanged | pass | live: {} 'missing field: title'; title '' / 5; [] 'must be a JSON object'; bogus key 'unknown field(s): bogus'; '{bad' invalid JSON: all 400; file bytes unchanged; suite ok |
| 8 | DELETE /tasks/1 -> 204 empty; GET then 404; DELETE again 404 | pass | live: 204 with empty body, no Content-Type; then 404, 404; suite ok |
| 9 | GET /nope 404 JSON; DELETE /tasks 405 + Allow; PUT /tasks/1 405 | pass | live: 404 {'error':'not found'}; DELETE /tasks 405 Allow 'GET, POST'; PUT /tasks/2 405 Allow 'GET, PATCH, DELETE'; suite ok |
| 10 | library <-> HTTP share the file | pass | live: task added via TaskStore(F) visible at GET /tasks/2; HTTP PATCH visible via TaskStore(F).get(1); suite ok |
| 11 | CLI serve prints 'Serving on http://127.0.0.1:<port>' within 5 s; GET /tasks 200 | pass | live: stdout 'Serving on http://127.0.0.1:49767' after 0.07 s; GET /tasks 200; process stopped by SIGTERM, none left running; suite ok |
| 12 | 20 concurrent POSTs -> all 201, ids exactly 1..20 | pass | live (CLI-started server): 20 threads, statuses {201}, ids sorted == 1..20, store ids 1..20; suite ok |

## Preservation
| Behavior | Status | Evidence |
|---|---|---|
| S0: --version 'todo 0.1.0' exit 0; no args -> usage, exit 2; both discovery forms green | pass | CLI: rc 0 'todo 0.1.0'; no args rc 2 usage now lists {add,list,done,rm,serve}; discover -s tests -t .: Ran 105 OK; discover -s tests: Ran 105 OK; s0 suite 11 tests ok |
| S1: store suite | pass | tests.acceptance.s1: 20 ok |
| S2: CLI suite + quick add/list | pass | tests.acceptance.s2: 14 ok; CLI add rc 0 'Added task 1: CLI X'; list rc 0 '1 [ ] CLI X' |
| S4 acceptance tests byte-identical to harness/S4-tests | pass | git diff --stat harness/S4-tests harness/S4 -- tests/acceptance/s4: empty; tests.acceptance.s4: 19 ok |

## Regressions
None.

## Contract issues
None.

## Notes
- testguard (informational, not a failure): STALE tests/acceptance/s0/test_s0_acceptance.py, an older copy of harness/S0-tests (1-line diff against harness/integration). Integration already has the fix; it resolves when S4 merges into integration.
- Side effect of that stale file: its a9 test runs `python -I -S` without -B, so running the suite created an untracked, git-ignored todo/__pycache__ in the qa-S4 worktree at 14:32:17. QA left it in place (no edits in that worktree). No tracked files changed.
- Each full suite run takes about 47 s, mostly because the S0 a6/a7 tests run the whole suite again inside a test, which now includes the S4 server and concurrency tests.
