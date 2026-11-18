# QA report: S2 (CLI add/list/done/rm)

**Status: PASS.** Worktree wt/qa-S2 @ acf5243 (harness/S2). Every command run with PYTHONDONTWRITEBYTECODE=1 (and -B for inline scripts); temp HOME, TODO_FILE unset, temp store files; no tracked files changed; real ~/.todo.json absent before and after.

## Test runs
- `python -m unittest discover -s tests -t .`: Ran 77 tests, OK (s0: 11, s1: 20, s2: 14, plus developer tests)
- `python -m unittest discover -s tests`: Ran 77 tests, OK
- `git diff --stat harness/S2-tests harness/S2 -- tests/acceptance/s2`: empty

## Acceptance
| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | add 'Buy milk' -> 'Added task 1: Buy milk'; list line 1 starts '1 [ ] Buy milk' | pass | CLI: add rc 0 stdout 'Added task 1: Buy milk'; list rc 0 stdout '1 [ ] Buy milk'; test_a1_add_then_list ok |
| 2 | list on nonexistent file -> 'No tasks.'; list --json -> [] | pass | CLI: rc 0 'No tasks.'; --json rc 0 '[]'; file not created by reads; test_a2_list_empty_nonexistent_file ok |
| 3 | list --json after A,B: ids [1,2], titles, done False, created present | pass | CLI: [{id 1,title A,done false,created ...},{id 2,title B,done false,created ...}]; test_a3_list_json_shape ok |
| 4 | done 1 -> 'Completed task 1: A'; list '1 [x] A' / '2 [ ] B' | pass | CLI: rc 0; list '1 [x] A|2 [ ] B'; test_a4_done_marks_complete ok |
| 5 | rm 2 -> 'Deleted task 2: B'; list --json ids [1] | pass | CLI: rc 0; --json ids [1]; test_a5_rm_deletes ok |
| 6 | done 42 / rm 42 -> exit 1, 'task 42 not found', stdout empty, no traceback | pass | CLI: both rc 1, stderr 'error: task 42 not found', stdout empty, 0 Traceback; test_a6_unknown_id_errors ok |
| 7 | done abc -> exit 2 with 'invalid'; add with no title -> exit 2 | pass | CLI: done abc rc 2 "invalid int value: 'abc'"; add rc 2 'the following arguments are required: title'; rm 1.5 rc 2; test_a7_* (2 tests) ok |
| 8 | add '' / '   ' -> exit 1, stderr starts 'error:'; no task created | pass | CLI: both rc 1 'error: title must not be empty'; list --json []; test_a8_blank_title_rejected ok |
| 9 | TODO_FILE fallback without --file | pass | CLI: TODO_FILE=<tmp>/env.json add X rc 0; TaskStore(env.json).list() -> [X]; --file beats TODO_FILE (Y went to arg.json); temp HOME has no .todo.json; test_a9_* (2 tests) ok |
| 10 | invalid JSON -> list exit 1, 'error:', no traceback | pass | CLI: rc 1 'error: invalid JSON in <path>: ...'; wrong structure [1] -> rc 1 'error: invalid store file <path>: ...'; no Traceback; test_a10_invalid_json_file ok |
| 11 | in-process main([...,'add','Z']) == 0, stdout capturable | pass | python -B -c: rc 0, captured 'Added task 1: Z\n'; main(['done','9']) rc 1, stderr 'error: task 9 not found'; test_a11_in_process_main ok |
| 12 | CLI writes visible to library | pass | CLI add X; TaskStore(tmp).get(1)['title'] == 'X'; test_a12_cli_writes_visible_to_library ok |

## Preservation
| Behavior | Status | Evidence |
|---|---|---|
| S0: --version -> 'todo 0.1.0', exit 0 | pass | CLI: rc 0 stdout 'todo 0.1.0'; tests.acceptance.s0: 11 tests ok |
| S0: no subcommand -> usage on stderr, exit 2, stdout empty; --bogus exit 2 | pass | CLI: no args rc 2 'usage: todo ... a command is required'; '--file X' alone rc 2; --bogus rc 2 |
| S0: both discovery forms exit 0 | pass | discover -s tests -t .: Ran 77 tests OK; discover -s tests: Ran 77 tests OK |
| S1: store behaviors (acceptance suite) | pass | tests.acceptance.s1: 20 tests ok; developer tests/test_store.py ok |
| S2 acceptance tests byte-identical to harness/S2-tests | pass | git diff --stat harness/S2-tests harness/S2 -- tests/acceptance/s2: empty |

## Regressions
None.

## Contract issues
None.

## Notes
- Untracked, git-ignored todo/__pycache__ (__init__, cli, errors, store .pyc; no commands.pyc) is present in the qa-S2 worktree, mtime 14:26:12. QA left it in place (no edits in the worktree). It is likely not from QA: every QA run set PYTHONDONTWRITEBYTECODE=1 and imported todo.commands. It does not affect the results.
