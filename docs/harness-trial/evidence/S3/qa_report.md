# QA report: S3 (due date + priority, filter/sort)

**Status: PASS.** **S5 follow-up: PASS** (S5 items 3 and 7, S3 cases). Worktree wt/qa-S3 @ 077a5a1 (harness/S3 = integration S0+S1+S2+S4+S5 + S3). PYTHONDONTWRITEBYTECODE=1 throughout (inline scripts with -B); temp HOME and store files; live server stopped afterwards; no tracked or ignored files created in the worktree.

## Test runs
- `python -m unittest discover -s tests -t .`: Ran 181 tests, OK (skipped=1)
- `python -m unittest discover -s tests`: Ran 181 tests, OK (skipped=1)
- Per suite: s0 11, s1 20, s2 14, s3 26 (all run, REST item 11 not skipped), s4 19, s5 23
- The one skip is s5 `test_a7_pre_s3_nonempty_due_rejected`, which applies only before S3 is merged
- `git diff --stat harness/S3-tests harness/S3 -- tests/acceptance/s3`: empty; testguard OK

## Acceptance
| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | add due/priority persists across instances; CLI list line with both suffixes | pass | live check /tmp/qa-s1-scripts/s3live.py: new TaskStore(p).get(1) due '2026-12-01' priority 'high'; CLI list ['1 [ ] Pay rent (due 2026-12-01, priority high)']; test_a1_* (2) ok |
| 2 | defaults due None / priority 'normal' (also with explicit None) | pass | live: both adds -> due None, priority 'normal'; test_a2_defaults ok |
| 3 | invalid due/priority rejected; store unchanged | pass | live: due 2026-02-30, 2026-1-5, tomorrow, 20261201; priority HIGH, urgent, 1 -> all ValidationError; file bytes unchanged; 2028-02-29 accepted; test_a3 ok |
| 4 | update due/priority persist; priority=None and update(99, priority='bad') -> ValidationError | pass | live: due 2027-01-01 + priority low persisted, due=None cleared (priority kept); priority=None -> ValidationError; update(99,'bad') -> ValidationError (not TaskNotFound); CREATE_FIELDS (title,due,priority), UPDATE_FIELDS (title,done,due,priority); test_a4_* (3) ok |
| 5 | pre-S3 file backfilled on read, file not rewritten | pass | live: hand-written file -> (1,None,'normal'),(2,None,'normal'); after list(), list(sort=...) and CLI list: bytes and mtime unchanged; test_a5 ok |
| 6 | status filter partitions; status='all' / sort='title' rejected | pass | live: open [1,3], done [2,4]; both bad values -> ValidationError; test_a6_* (2) ok |
| 7 | sort due [3,1,2], priority [2,3,1]; equal created -> id; status+sort combine | pass | live: due [3,1,2]; priority [2,3,1]; equal-created file in order [3,1,2] -> [1,2,3]; open+priority [4,3,1]; test_a7_* (5) ok |
| 8 | CLI add --due/--priority; --priority urgent exit 2; --due 2026-13-01 exit 1 | pass | live: rc 0 'Added task 1: X', stored due/priority; urgent rc 2; bad due rc 1 "error: due is not a valid calendar date: '2026-13-01'", stdout empty, no traceback, no file/task created; test_a8_* (3) ok |
| 9 | list --status done empty -> 'No tasks.'; --sort bogus exit 2; --status open --sort due --json | pass | live: 'No tasks.'; rc 2; JSON [(3,'2026-12-01','normal'),(1,'2026-12-05','low'),(4,None,'high')], each element has due+priority; text --sort due matches the Interface example lines; test_a9_* (4) ok |
| 10 | default task line has no suffix | pass | live: stdout exactly '1 [ ] Plain\n2 [x] Two\n'; test_a10 ok |
| 11 | REST POST with due/priority 201; bad due/priority POST/PATCH 400; PATCH due null 200 | pass | live CLI server: POST -> 201 due/priority set; POST and PATCH {due:'bad'} / {priority:'urgent'} -> 400 {error}; PATCH {due:null} -> 200 due null, persisted; test_a11_* (3) ok, not skipped (todo.server present) |

## Preservation
| Behavior | Status | Evidence |
|---|---|---|
| S0: both discovery forms green | pass | discover -s tests -t .: Ran 181, OK (skipped=1); discover -s tests: Ran 181, OK (skipped=1). The one skip is s5 test_a7_pre_s3_nonempty_due_rejected (applies only before S3) |
| S1 suite (key-subset, unknown-field rejection, id rules, list() ascending id) | pass | tests.acceptance.s1: 20 ok |
| S2 suite (Added/Completed/Deleted lines, list lines, No tasks., exit codes) | pass | tests.acceptance.s2: 14 ok; live default lines byte-identical to S2 (A10) |
| S4 suite (status codes, {error}, bogus/color keys 400) | pass | tests.acceptance.s4: 19 ok; live: GET /tasks/99 404 {'error':'task 99 not found'}, POST bogus 400, PATCH color 400, DELETE 204, GET /tasks 200 |
| S5 suite | pass | tests.acceptance.s5: 23 (22 ok, 1 pre-S3-only skip) |
| S3 acceptance tests byte-identical to harness/S3-tests | pass | git diff --stat harness/S3-tests harness/S3 -- tests/acceptance/s3: empty; testguard OK (no stale files) |

## S5 follow-up (blocked until S3)
| Item | Status | Evidence |
|---|---|---|
| S5 #3: with S3 merged, tasks with due/priority (and one with neither) round-trip exactly | pass | live: store A with (due+high), (due, done), (low only), (neither) -> CLI export 'Exported 4 tasks', import into empty B 'Imported 4 tasks, skipped 0 duplicates'; TaskStore(A).list() == TaskStore(B).list() True; CSV rows include due/priority cells, e.g. '3,prio only,false,...,,low'; tests.acceptance.s5 test_a3_due_priority_round_trip ok |
| S5 #7 (S3 cases): invalid due/priority rows -> exit 1, 'error:' with :<line>:, no traceback, store unchanged even after valid rows | pass | live: due=2026-02-30 after a valid row -> rc 1 'error: <file>:3: due is not a valid calendar date'; priority=urgent and priority=HIGH after a valid row -> rc 1 '<file>:3: priority must be one of ...'; due=tomorrow -> '<file>:2: ...'; no traceback; store bytes unchanged in every case; blank due/priority cells -> defaults (due None, priority normal); tests.acceptance.s5 test_a7_s3_invalid_due_rejected, test_a7_s3_invalid_priority_rejected, test_a7_invalid_rows_rejected_all_or_nothing ok |

## Regressions
None.

## Contract issues
None.
