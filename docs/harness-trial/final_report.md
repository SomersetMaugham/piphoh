# Final report: todo-app (pipelined-team-harness trial)

## Built (slice -> PRD)
| Slice | PRD | Status |
|---|---|---|
| S0 Walking skeleton | 2 (--version), 6 | merged, QA pass |
| S1 JSON store | 1 | merged, QA pass |
| S2 CLI add/list/done/rm | 2 | merged, QA pass |
| S3 Due/priority, filter/sort | 3 | merged, QA pass (+S5 follow-up pass) |
| S4 REST API | 4 | merged, QA pass |
| S5 CSV export/import | 5 | merged, QA pass |

Integration branch `harness/integration`: 181 tests, OK (1 intentional skip). Not merged to `main` (needs user approval).

## Final independent QA (final_qa.md): PASS, with gaps
1. CSV import skips rows whose id exists in the store even when they are different tasks (data loss by design of S5 contract).
2. `--file` must precede the subcommand; README has no usage.
3. Tracebacks: `serve --port 99999`; `export` on a task without `created`.
4. `~` not expanded in TaskStore(path)/TODO_FILE.
5. Minor: no CLI edit for due/priority; REST ignores ?status/?sort; strict CSV headers.
Suggested next slices: S6 import conflict policy (--on-conflict skip|renumber), S7 error hardening (port range, malformed records, ~ expansion), S8 README + `edit` command.

## Plan vs actual
Scheduler estimate (2 dev + 2 qa): 10 units. Actual: ~35 minutes wall clock, 6 slices, 11 fresh subagent dispatches + ~14 follow-ups to existing subagents.
Deviations: 3 hidden cross-slice deps found mid-run (S3->S2, S5->S2/S3, S4 needed S2's --file); 4 registry merge conflicts (all one-line).

# Round 2 (follow-up slices S6–S9, approved by the user)
| Slice | PRD | Status |
|---|---|---|
| S6 Import conflict policy | 7 | merged, QA pass (renumber instead of drop) |
| S7 Error hardening | 8, 9 | merged, QA pass (no tracebacks; ~; --file anywhere) |
| S8 edit command | 10 | merged, QA pass |
| S9 README | 11 | merged, QA pass + doc fix |
Integration: 267 tests OK (1 intentional skip). All round-1 final-QA findings fixed.

## Final independent QA round 2 (final_qa_round2.md): accept with caveats
1. Concurrent writers (parallel CLI runs, or CLI + serve) lose updates: no file locking. Not in PRD, but README invites mixed use.
2. Re-importing the same foreign CSV duplicates renumbered rows (also noted by S6 slice QA).
3. Import can reuse ids of deleted tasks (README says ids are never reused).
4. HEAD /tasks -> 501 HTML; non-UTF-8 store -> "unexpected UnicodeDecodeError"; small message/consistency nits.
Suggested next slices: S10 cross-process file locking; S11 import idempotency (match created+title against all tasks; never reuse deleted ids); S12 polish (HEAD, UTF-8 error, plurals, PATCH priority null).
