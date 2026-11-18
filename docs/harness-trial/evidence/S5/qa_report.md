# QA report: S5 (CSV export/import)

**Status: PASS (non-S3 items); items 3 and 7's S3 sub-case BLOCKED until S3 merges.** Worktree wt/qa-S5 @ 0a62616 (harness/S5 = S0+S1+S2+S5; S3 and S4 not present). Every command run with PYTHONDONTWRITEBYTECODE=1 and -B, temp HOME, TODO_FILE unset, temp store/CSV files; no files in the worktree changed; real ~/.todo.json absent before and after.

## Test runs
- `python -m unittest discover -s tests -t .`: Ran 122 tests, OK (skipped=3)
- `python -m unittest discover -s tests`: Ran 122 tests, OK (skipped=3)
- Per slice: s0 11 OK; s1 20 OK; s2 14 OK; s5 23 OK (skipped=3: test_a3_due_priority_round_trip, test_a7_s3_invalid_due_rejected, test_a7_s3_invalid_priority_rejected — reason 'requires S3 (due/priority not in TaskStore.CREATE_FIELDS yet)')
- `git diff --stat harness/S5-tests HEAD -- tests/acceptance/s5`: empty; s0/s1/s2 acceptance tests identical to harness/integration

## Acceptance
| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Library A (Buy milk; 'Say "hi", world'+newline, done) -> export out.csv 'Exported 2 tasks to out.csv'; import into empty B 'Imported 2 tasks, skipped 0 duplicates'; B.list()==A.list() | pass | CLI: export rc 0 'Exported 2 tasks to out.csv'; import rc 0 'Imported 2 tasks, skipped 0 duplicates'; TaskStore(B).list()==TaskStore(A).list() True (embedded quotes/comma/newline preserved, done True kept); test_a1_export_import_round_trip ok |
| 2 | Header 'id,title,done,created,due,priority'; done 'false'/'true'; empty store -> header only, 'Exported 0 tasks to ...' | pass | CLI: file bytes start 'id,title,done,created,due,priority\r\n'; row '1,Buy milk,false,<created>,,' (CRLF, pre-S3 empty due/priority); title with quotes written as '"Say ""hi"", world\nsecond"'; empty store rc 0 'Exported 0 tasks to e.csv', file = header line only, store file not created; test_a2_header_and_done_strings ok; test_a2_empty_store_header_only ok |
| 3 | With S3 merged: tasks with due/priority (and one with neither) round-trip exactly | blocked | S3 is not on this branch (TaskStore.CREATE_FIELDS == ('title',)); test_a3_due_priority_round_trip skipped: 'requires S3 (due/priority not in TaskStore.CREATE_FIELDS yet)'; Pre-S3 related behaviour observed: CSV 'title,due' with 'X,2026-12-01' -> rc 1 'error: due.csv:2: unknown field(s): due', store not created (matches Interface rule) |
| 4 | Re-import same file -> 'Imported 0 tasks, skipped 2 duplicates', B unchanged; id 5 twice -> first imported, second skipped | pass | CLI: re-import rc 0 'Imported 0 tasks, skipped 2 duplicates'; '5,First/5,Second' -> 'Imported 1 tasks, skipped 1 duplicates', list '5 [ ] First'; row '1,Replacement,true' into store holding id 1 -> skipped, task 1 still 'Buy milk' open; test_a4_reimport_skips_all ok; test_a4_same_id_twice_in_file ok; test_a4_existing_task_never_overwritten ok |
| 5 | Title-only CSV (3 rows) into store with next_id 4 -> ids 4,5,6, done false, created within 5 s; next add gets 7 | pass | CLI: rc 0 'Imported 3 tasks, skipped 0 duplicates'; list --json ids 4,5,6 titles Alpha/Beta/Gamma done false created == current UTC second; add -> 'Added task 7: Next'; test_a5_title_only_gets_new_ids ok |
| 6 | Imported id 10 into empty store -> next add gets 11 | pass | CLI: import 'id,title/10,Ten' rc 0; add -> 'Added task 11: After'; test_a6_imported_id_bumps_next_id ok |
| 7 | Invalid rows (done=maybe, id=abc, id=0, created=yesterday, blank title; S3: due=2026-02-30) -> exit 1, 'error:' with ':<line>:', no traceback, store bytes unchanged even after valid rows | pass | CLI (valid row on line 2, bad row on line 3, store pre-populated; sha256 compared): all rc 1, stdout empty, 0 Traceback, store unchanged. stderr: 'error: bad.csv:3: done must be true/false/1/0, got 'maybe'' / 'id must be a positive integer, got 'abc'' / '... got '0'' / 'created must look like YYYY-MM-DDTHH:MM:SSZ' / 'title must not be empty' (also whitespace-only title); done values TRUE/0/blank accepted case-insensitively (-> True/False/False); test_a7_invalid_rows_rejected_all_or_nothing ok (5 subtests); test_a7_pre_s3_nonempty_due_rejected ok; S3 sub-case due=2026-02-30 (and priority=urgent) BLOCKED until S3 merges: test_a7_s3_invalid_due_rejected, test_a7_s3_invalid_priority_rejected skipped |
| 8 | Header without title, unknown column color, or empty file -> exit 1 'error:'; nonexistent import file -> exit 1 'error:' with path | pass | CLI: rc 1 'error: h1.csv:1: header must contain a 'title' column'; rc 1 'error: h2.csv:1: unknown column 'color''; rc 1 'error: h3.csv: empty file (no header)'; duplicate column rc 1 'error: h4.csv:1: duplicate column 'title''; missing file rc 1 'error: cannot read /nonexistent/zzz.csv: No such file or directory'; store bytes unchanged; import of missing file into absent store does not create it; test_a8_* (4 tests) ok |
| 9 | Export overwrites an existing file; export into a nonexistent dir -> exit 1 'error:' | pass | CLI: 100-line junk file overwritten, 0 'junk' lines remain, rc 0 'Exported 2 tasks to ov.csv'; 'export nodir/out.csv' rc 1 'error: cannot write nodir/out.csv: No such file or directory', dir not created; test_a9_export_overwrites ok; test_a9_export_to_missing_dir ok |
| 10 | UTF-8 BOM CSV imports correctly; non-ASCII titles round-trip | pass | CLI: BOM + 'title,done/Café,true' -> rc 0 'Imported 1 tasks, skipped 0 duplicates', task {title 'Café', done true}; '日本語 ☕ Ünï 🚀' export/import -> lists equal; test_a10_bom_csv_imports ok; test_a10_non_ascii_round_trip ok |
| 11 | In-process export_csv(store,p)==2; import_csv(store2,p)=={'imported':2,'skipped':0} | pass | python -B -c: export_csv -> 2; import_csv -> {'imported': 2, 'skipped': 0}; COLUMNS == ('id','title','done','created','due','priority'); TaskStore.restore([]) -> {'imported': [], 'skipped': []}; test_a11_export_import_functions ok; test_a11_columns_constant ok |

## Preservation
| Behavior | Status | Evidence |
|---|---|---|
| S0: --version, usage exit 2, both discovery forms | pass | CLI: --version rc 0 'todo 0.1.0'; no args rc 2 'usage: ... {add,list,done,rm,export,import} ... a command is required'; discover -s tests -t .: Ran 122 tests OK (skipped=3); discover -s tests: Ran 122 tests OK (skipped=3); tests.acceptance.s0: 11 ok |
| S1: task shape, id allocation by add (no reuse), unknown-field rejection | pass | tests.acceptance.s1: 20 ok; python -B: add a,b; delete 2; add c -> id 3; add('x', bogus=1) and add('x', due=...) -> ValidationError 'unknown field(s): ...' |
| S2: dispatch, exact Added/Completed/Deleted lines, list output, error:/exit codes | pass | tests.acceptance.s2: 14 ok; CLI: 'Added task 1: Buy milk' / '1 [ ] Buy milk' / 'Completed task 1: Buy milk' / '1 [x] Buy milk' / 'Deleted task 1: Buy milk'; done 42 rc 1 'error: task 42 not found' |
| S3 preservation (validation rules, defaults) | not_applicable | S3 not on this branch |
| S4 preservation (REST shape) | not_applicable | S4 not on this branch (diff harness/integration..HEAD touches only S5 files) |
| Acceptance tests byte-identical to their QA branches | pass | git diff --stat harness/S5-tests HEAD -- tests/acceptance/s5: empty; git diff --stat harness/integration HEAD -- tests/acceptance/{s0,s1,s2}: empty |

## Regressions
None.

## Contract issues
- Acceptance 3 and the due=2026-02-30 sub-case of 7 depend on S3, which is not on harness/S5; they are blocked (tests skip) and must be re-verified once S3 and S5 are both merged (S3/S5 both edit store.py/_validate_create).
- TaskStore.restore(records) record format (raw strings vs parsed values, id None vs absent) is not specified in the contract; only covered indirectly via import_csv/CLI.

## Notes
- Status 'pass' covers every non-S3 acceptance item; items 3 and 7(S3 sub-case) are 'blocked until S3 merges', not passed.
- Export into a read-only (0555) dir succeeded because QA runs as root; unwritable-path handling was verified via the nonexistent-dir case instead.
- Worktree wt/qa-S5 @ 0a62616 left untouched: git status shows no changes and no __pycache__ (only the ignored .harness/ dir). All runs used PYTHONDONTWRITEBYTECODE=1 and -B, temp HOME, TODO_FILE unset; real ~/.todo.json absent before and after.
