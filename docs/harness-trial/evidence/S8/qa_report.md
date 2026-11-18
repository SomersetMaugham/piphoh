# QA report: S8 (`edit` command)

**Status: PASS.** Worktree wt/qa-S8 @ 65a9b9f (detached harness/S8 = S0-S5 + S8). PYTHONDONTWRITEBYTECODE=1 throughout; live CLI checks (/tmp/qa-s8/live.py, run with -B) used temp HOME and store files; nothing written to the worktree.

## Test runs
- `python -m unittest discover -s tests -t .`: Ran 203, OK (skipped=1)
- `python -m unittest discover -s tests`: Ran 203, OK (skipped=1)
- Per suite: s0 11, s1 20, s2 14, s3 26, s4 19, s5 23 (1 pre-S3 skip), s8 16
- `git diff --stat harness/S8-tests HEAD -- tests/acceptance`: empty; s0-s5 tests and todo/cli.py unchanged vs integration

## Acceptance
| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | add 'Buy milk'; edit 1 --title/--due/--priority -> 'Updated task 1: Buy oat milk'; list --json fields set, done false, created unchanged | pass | live /tmp/qa-s8/live.py: rc 0, stdout 'Updated task 1: Buy oat milk\\n', stderr empty; task 1 (title 'Buy oat milk', due '2026-12-01', priority 'high', done False); created identical to before edit; tests.acceptance.s8 test_a1 ok |
| 2 | --no-due clears due (priority kept); --priority low changes only priority; --title '  Trimmed  ' -> 'Trimmed' | pass | live: --no-due -> due None, priority 'high', list line '1 [ ] Buy oat milk (priority high)' (matches Example 2); --priority low -> title/due unchanged; --title '  Trimmed  ' -> stdout 'Updated task 1: Trimmed', stored 'Trimmed'; tests.acceptance.s8 test_a2_* ok |
| 3 | edit 1 with no options -> exit 1, exact 'nothing to change' message, store bytes unchanged | pass | live: rc 1, stdout empty, stderr exactly 'error: nothing to change (use --title, --due, --no-due or --priority)\\n'; file bytes unchanged; tests.acceptance.s8 test_a3 ok |
| 4 | --due 2026-02-30 / --due tomorrow / --title '  ' -> exit 1, 'error:' (S3/S1 messages), store unchanged | pass | live: rc 1 each, stdout empty, no traceback, bytes unchanged; messages "error: due is not a valid calendar date: '2026-02-30'" (matches Example 3), "error: due must be a date in YYYY-MM-DD format, got 'tomorrow'", 'error: title must not be empty'; tests.acceptance.s8 test_a4 ok |
| 5 | --due + --no-due, --priority urgent, id abc -> exit 2, no Traceback | pass | live: rc 2 each, no traceback, store unchanged; 'argument --no-due: not allowed with argument --due', "argument --priority: invalid choice: 'urgent'", "argument id: invalid int value: 'abc'"; tests.acceptance.s8 test_a5 ok |
| 6 | edit 42 --title x -> exit 1, 'error: task 42 not found', stdout empty | pass | live: (1, '', 'error: task 42 not found\\n'); tests.acceptance.s8 test_a6 ok |
| 7 | list after item 1 shows the S3 suffix line; other tasks unchanged | pass | live: first line '1 [ ] Buy oat milk (due 2026-12-01, priority high)'; tasks 2 (due+low) and 3 (default) identical in list --json before and after edit; tests.acceptance.s8 test_a7 ok |

## Preservation
| Behavior | Status | Evidence |
|---|---|---|
| Both discovery forms green | pass | discover -s tests -t .: Ran 203, OK (skipped=1); discover -s tests: Ran 203, OK (skipped=1). The skip is s5 test_a7_pre_s3_nonempty_due_rejected (pre-S3 only) |
| S0 usage exit 2 / --version | pass | tests.acceptance.s0: 11 ok; live: no command -> rc 2 'todo: error: a command is required'; --version -> 'todo 0.1.0' rc 0 |
| S1 store via suite | pass | tests.acceptance.s1: 20 ok |
| S2 add/list/done/rm output and exit codes | pass | tests.acceptance.s2: 14 ok; live: 'Added task 1: A', '1 [ ] A\\n2 [ ] B', 'Completed task 2: B', '2 [x] B', 'Deleted task 1: A', rm missing -> rc 1 'error: task 1 not found', done abc -> rc 2 |
| S3 list suffixes, validation messages, update semantics | pass | tests.acceptance.s3: 26 ok; live: --sort due lines exact ('3 [ ] Z (due 2026-12-01)', '1 [ ] X (due 2026-12-05, priority low)', '2 [ ] Y (priority high)'); add --due 2026-13-01 -> rc 1 exact S3 message; editing a done task keeps done ('1 [x] R') |
| S4/S5 suites | pass | tests.acceptance.s4: 19 ok; tests.acceptance.s5: 23 (22 ok, 1 pre-S3 skip) |
| S8 acceptance tests untouched; scope respected | pass | git diff --stat harness/S8-tests HEAD -- tests/acceptance: empty; git diff 7ec10fd HEAD -- tests/acceptance/s0..s5 todo/cli.py: empty; production change only in todo/commands.py (cmd_edit + register), plus tests/test_edit.py |

## Regressions
None.

## Contract issues
None.

## Notes
- Worktree wt/qa-S8 @ 65a9b9f (detached, harness/S8). PYTHONDONTWRITEBYTECODE=1; live checks with -B from /tmp/qa-s8 against temp HOME/stores (temp HOME left empty); git status --short --ignored shows only .harness/ (no compiled files created).
- Observation (not a failure): tests.acceptance.s0 takes ~53 s alone (the full suite ~80-90 s), the same as in earlier slices.
