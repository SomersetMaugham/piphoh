# QA report: S1 (JSON store library API)

**Status: PASS.** Worktree wt/qa-S1 @ e665ef9 (harness/S1). Every command run with PYTHONDONTWRITEBYTECODE=1; no tracked files changed.

## Test runs
- `python -m unittest discover -s tests -t .`: Ran 47 tests, OK
- `python -m unittest discover -s tests`: Ran 47 tests, OK
- `git diff --stat harness/S1-tests harness/S1 -- tests/acceptance/s1`: empty (byte-identical)

Behavior was also checked directly with a script outside the worktree (`/tmp/qa-s1-scripts/check.py`, run with temp HOME and temp store paths).

## Acceptance
| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | add then new instance list(); file valid JSON | pass | check.py A1: new TaskStore(p).list() -> [{'id':1,'title':'Buy milk','done':False,'created':...}]; file top-level keys next_id/tasks/version; test_a1_add_persists_and_new_instance_lists ok |
| 2 | add() return keys/types; created format and within 5 s | pass | check.py A2: types int/str/bool/str; regex match True; age 0.96 s; test_a2_add_return_shape_and_created ok |
| 3 | title stripped; bad titles and unknown fields -> ValidationError (TodoError, ValueError) | pass | check.py A3: '  x  ' -> 'x'; '', '   ', None, 5 -> ValidationError (isinstance TodoError and ValueError True); add('x', bogus=1) -> ValidationError 'unknown field(s): bogus'; no task created by failures; test_a3_* (3 tests) ok |
| 4 | list() on missing path is [] and creates no file; ids [1,2,3] | pass | check.py A4: [] / exists False; ids [1,2,3]; test_a4_* (2 tests) ok |
| 5 | complete idempotent and persisted | pass | check.py A5: True, True, new instance get(1)['done'] True; test_a5_complete_idempotent_and_persisted ok |
| 6 | delete(2) returns task; get(2) TaskNotFound task_id 2; ids [1,3] | pass | check.py A6: delete -> {'id':2,'title':'b',...}; e.task_id 2, 'task 2 not found'; ids [1,3]; test_a6_delete_returns_task_then_gone ok |
| 7 | ids never reused | pass | check.py A7: add,add,delete(2),add -> id 3; next_id in file 4; test_a7_ids_never_reused ok (also across instances: id 4 after deleting 3) |
| 8 | get/complete/delete/update unknown id -> TaskNotFound, message exact | pass | python -c: all four methods -> task_id 99, str 'task 99 not found'; test_a8_unknown_id_raises_task_not_found ok |
| 9 | update title/done persist; invalid updates -> ValidationError | pass | check.py A9: new instance get(1) -> title 'New', done False; update(1) 'no fields to update'; done=1 and done='true' 'done must be a boolean'; title='' 'title must not be empty'; color='red' 'unknown field(s): color'; update(99, color='red') -> ValidationError (fields validated before id); test_a9_* (2 tests) ok |
| 10 | returned dicts are copies | pass | check.py A10: mutating add/get/list results leaves get(1)['title'] == 'orig'; test_a10_returned_dict_is_a_copy ok |
| 11 | path resolution: env, explicit beats env, default HOME/.todo.json | pass | check.py A11: TODO_FILE -> PosixPath equal to env path; explicit arg wins; no env, HOME=tmp -> <tmp>/home/.todo.json; test_a11_* (3 tests) ok; real ~/.todo.json absent before and after |
| 12 | invalid JSON -> StoreError with path | pass | check.py A12: StoreError 'invalid JSON in /tmp/.../bad.json: ...'; wrong structure ([1,2]) -> StoreError 'invalid store file <path>: top level must be an object'; test_a12_invalid_json_raises_store_error_with_path ok |
| 13 | parent dir created on first write | pass | check.py A13: tmp/sub/dir/t.json created, version 1, no leftover temp files in dir; test_a13_parent_dir_created_on_first_write ok |
| 14 | re-exports from todo | pass | check.py A14: from todo import TaskStore, TodoError, TaskNotFound, ValidationError, StoreError ok; same objects as todo.store/todo.errors; CREATE_FIELDS ('title',), UPDATE_FIELDS ('title','done'); test_a14_public_reexports ok |

## Preservation
| Behavior | Status | Evidence |
|---|---|---|
| S0: python -m todo --version prints 'todo 0.1.0', exit 0 | pass | stdout 'todo 0.1.0', rc 0 |
| S0: no args -> usage on stderr, exit 2, empty stdout; --bogus -> exit 2 with usage | pass | no args: rc 2, stdout 0 bytes, stderr 'usage: todo ...'; --bogus: rc 2, stderr 'usage: todo ...unrecognized arguments' |
| S0: main(['--version']) raises SystemExit(0) | pass | python -c: SystemExit 0 |
| S0: python -m unittest discover -s tests -t . exits 0 | pass | Ran 47 tests ... OK (20 acceptance.s1 tests ok) |
| S0: python -m unittest discover -s tests exits 0 | pass | Ran 47 tests ... OK |
| S0: no non-stdlib imports under todo/ | pass | grep of imports under todo/: only stdlib and todo-internal modules |
| S1 acceptance tests byte-identical to harness/S1-tests | pass | git diff --stat harness/S1-tests harness/S1 -- tests/acceptance/s1: empty |

## Regressions
None.

## Contract issues / notes
- S0 acceptance tests (tests/acceptance/s0) are not on harness/S1, so S0 preservation was checked by hand (commands above), not by the S0 suite.
- Atomic write (os.replace) and the threading.Lock are in the interface but not in the numbered Acceptance; only checked indirectly (no leftover temp files).
- A first run of the check script used `python3 -I`, which ignores PYTHONDONTWRITEBYTECODE and created an untracked, git-ignored `todo/__pycache__` in the worktree. It was deleted right away; `git status` was clean before and after.
