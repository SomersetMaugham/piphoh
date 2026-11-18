# Final QA acceptance: todo-app (branch harness/integration)

Reviewer: independent final pass, judged only against `.harness/brief.md`.
Environment: Python 3.13, `PYTHONDONTWRITEBYTECODE=1`, `HOME` and every store/CSV file in `mktemp -d` dirs, `~/.todo.json` never touched, all servers stopped, `git status` clean afterwards.

**Overall verdict: PASS.** All 6 PRD points work. Errors give clear messages and the right exit and HTTP codes. I found no crash on any normal path. The remaining issues are edge cases plus one data-loss risk in CSV import (issue 1).

---

## 1. Library API (add/list/complete/delete, JSON persistence, configurable path) — PASS

Evidence (`from todo import TaskStore, ...`):
```
s.add("one")            -> {'id': 1, 'title': 'one', 'done': False, 'created': '2026-11-18T05:49:31Z', 'due': None, 'priority': 'normal'}
s.complete(1)           -> {... 'done': True ...}
s.delete(2)             -> returns deleted task; ids not reused (next_id stays 4 after rm)
TaskStore(same path).list() -> persisted data visible from a fresh instance
s.complete(42)          -> TaskNotFound: task 42 not found
s.add("")               -> ValidationError: title must not be empty
s.add("x", foo=1)       -> ValidationError: unknown field(s): foo
```
Default path: with `HOME=$T`, `python -m todo add "default path"` created `$T/.todo.json`. `TODO_FILE` env and `--file PATH` both work. Missing parent directories are created. Writes are atomic (temp file + `os.replace`).
Store errors: `{bad` -> `error: invalid JSON in ...: Expecting property name ...` (exit 1). `[]` -> `invalid store file ...: top level must be an object`. A directory path -> `cannot read ...: Is a directory`. An empty file -> `invalid JSON ... line 1 column 1`.

Gaps:
- `TaskStore("~/x.json")` does **not** expand `~`. It created a literal `./~/x.json` in the current directory. The same applies to `TODO_FILE="~/x.json"` when the shell leaves `~` unexpanded.
- `s.get("1")` (a string id) reports `task 1 not found` rather than a type error. The message looks wrong to the user.
- A hand-edited or legacy store file whose task has no `created` key loads fine, but `export` then crashes (see 5).

## 2. CLI (add/list/done/rm/--version, exit codes, clear errors) — PASS

```
$ todo --version            -> todo 0.1.0                          [exit 0]
$ todo add "Buy milk"       -> Added task 1: Buy milk              [exit 0]
$ todo list                 -> 1 [ ] Buy milk ...                  [exit 0]
$ todo done 2               -> Completed task 2: Pay rent          [exit 0] (repeat is idempotent)
$ todo rm 1                 -> Deleted task 1: Buy milk            [exit 0]
$ todo done 99 / rm 99      -> error: task 99 not found            [exit 1]
$ todo done abc             -> argparse: invalid int value: 'abc'  [exit 2]
$ todo add "   "            -> error: title must not be empty      [exit 1]
$ todo                      -> error: a command is required        [exit 2]
$ todo list (empty)         -> No tasks.
```
Unicode, quotes, commas and newlines in titles all round-trip. `todo add -- "-dash"` works.

Gaps:
- `--file` is a global option. It must come **before** the subcommand: `python -m todo list --file x.json` fails with `unrecognized arguments: --file ...` (exit 2). Users will hit this. `--help` shows it, but nothing points it out.
- The README contains only `# todo-app`. There are no usage docs: nothing about `TODO_FILE`, `--file` placement, `serve`, or the CSV format.
- A title starting with `-` needs `--`. This is standard argparse behaviour.

## 3. Due date + priority; list `--status` / `--sort` — PASS

```
$ todo add "Pay rent" --due 2026-12-01 --priority high -> Added task 2
$ todo list   -> 2 [ ] Pay rent (due 2026-12-01, priority high)
$ todo add x --due 2026-13-01 -> error: due is not a valid calendar date: '2026-13-01'      [exit 1]
$ todo add x --due tomorrow   -> error: due must be a date in YYYY-MM-DD format, got 'tomorrow' [exit 1]
$ todo add x --due 2026-2-3   -> rejected (strict YYYY-MM-DD)
$ todo add x --priority urgent -> invalid choice ... (choose from 'low', 'normal', 'high') [exit 2]
$ todo list --status open|done -> filters correctly
$ todo list --sort due        -> earliest first, undated last
$ todo list --sort priority   -> high, normal, low
$ todo list --sort created    -> by timestamp, id tiebreak
$ todo list --status bogus    -> invalid choice [exit 2]
```
Legacy tasks without `due`/`priority` are backfilled as `null`/`normal`.

Gaps:
- The CLI cannot set or clear due/priority on an existing task. There is no `edit` command; only the library and `PATCH` can do it. The PRD does not require an edit command, so this is a minor point.
- Priority `normal` is hidden in `list` output by design. Fine, but worth knowing.

## 4. REST API (`serve --port N`) — PASS

Live server `python -m todo --file $T/srv.json serve --port 18765`, tested with curl:
```
GET    /tasks                 -> 200 []
POST   /tasks {"title":..,"due":..,"priority":"high"} -> 201, Location: /tasks/1, task JSON
GET    /tasks/1               -> 200 task
GET    /tasks/99              -> 404 {"error": "task 99 not found"}
PATCH  /tasks/1 {"done":true} -> 200 updated; {"due":null} clears due
PATCH  /tasks/99              -> 404
PATCH  {"done":"yes"}         -> 400 {"error": "done must be a boolean"}
PATCH/POST bad JSON           -> 400 {"error": "request body must be valid JSON"}
PATCH  {}                     -> 400 no fields to update; {"id":5} -> 400 unknown field(s): id
POST   [1]                    -> 400 request body must be a JSON object
POST   {}                     -> 400 missing field: title
POST   bad due / bad priority / {"done":true} -> 400 with specific message
DELETE /tasks/2               -> 204; again -> 404
DELETE /tasks                 -> 405, Allow: GET, POST; PUT /tasks/1 -> 405, Allow: GET, PATCH, DELETE
GET    /tasks/abc, /nope      -> 404 {"error": "not found"}
```
Every response is `Content-Type: application/json`. The CLI sees changes made through the server. 50 concurrent POSTs (urllib, 20 threads) all returned 201, with 50 unique ids. Port already in use -> `error: cannot listen on 127.0.0.1:18766: Address already in use` (exit 1). SIGINT shuts down cleanly (exit 0). Corrupt store -> 500 with a JSON error explaining why. Requests are logged to stderr.

Gaps:
- `serve --port 99999` prints a raw Python traceback (`OverflowError: bind(): port must be 0-65535`) instead of a clean error.
- `GET /tasks?status=open` silently ignores the query, so the REST API has no filtering or sorting. The PRD does not require it, but a user might expect it to match the CLI.
- `todo list --file X` mistakes also apply to `serve`: `--file` must come before `serve`.

## 5. CSV export/import — PASS (with one notable gap)

```
$ todo export out.csv -> Exported 3 tasks to out.csv
  id,title,done,created,due,priority
  1,"Buy milk, eggs",true,2026-11-18T05:50:17Z,,normal
  2,"Say ""hi""",false,...,2026-12-01,high
  3,"multi\nline",false,...           (quoted correctly)
$ todo import out.csv (fresh store) -> Imported 3 tasks, skipped 0 duplicates; list --json is identical
$ todo import out.csv (again)       -> Imported 0 tasks, skipped 3 duplicates
$ minimal CSV `title,due,priority` with blank cells -> imports with defaults and fresh ids
```
Errors are all exit 1, give file:line, and import nothing (all-or-nothing confirmed: a bad row 3 left row 2 un-imported):
```
missing.csv  -> error: cannot read missing.csv: No such file or directory
unknown col  -> error: badcol.csv:1: unknown column 'colour'
no title col -> error: notitle.csv:1: header must contain a 'title' column
bad date     -> error: baddate.csv:3: due is not a valid calendar date: '2026-02-31'
bad priority -> error: badprio.csv:2: priority must be one of low, normal, high, got 'URGENT'
bad done     -> error: baddone.csv:2: done must be true/false/1/0, got 'yes'
empty file   -> error: empty.csv: empty file (no header)
non-UTF-8    -> error: cannot read bin.csv: not valid UTF-8
directory    -> cannot read d / cannot write d: Is a directory
export to missing dir -> error: cannot write /nonexistent/dir/x.csv: No such file or directory
export with corrupt store -> error: invalid JSON ... (no CSV file created)
```

Gaps:
- **Id collision drops tasks without warning.** I imported `out.csv` into a store that already held its own task 1 ("existing one"). The output was `Imported 2 tasks, skipped 1 duplicates`, and CSV task 1 ("Buy milk, eggs"), a *different* task, was never imported. Anyone merging an export from another machine or file into a non-empty store loses data, and the output calls it a "duplicate". Only the id is compared, never the content. A workaround exists (blank out the id column), but nothing tells the user about it.
- `export` crashes with a traceback (`KeyError: 'created'`) when the store has a task without `created`. The loader accepts such files, so it is reachable with hand-edited or legacy files.
- The header is case-sensitive (`Title,Due` -> `unknown column 'Title'`), and only `,` is accepted as a delimiter. Files from spreadsheet tools in some locales will be rejected. The messages are clear, though.
- `created` must be exactly `YYYY-MM-DDTHH:MM:SSZ`. After a spreadsheet re-saves the file, timestamps are often reformatted and the import is rejected.
- Grammar nit: "skipped 1 duplicates".

## 6. Tests via `python -m unittest discover -s tests` — PASS

```
$ HOME=$T python -m unittest discover -s tests
Ran 181 tests in 62.089s
OK (skipped=1)
```
The single skip is a deliberate "pre-S3 behaviour only (S3 is merged)" case. No files were left in the repo or in HOME.

---

## Most important issues

1. **CSV import silently drops tasks whose id is already in use** (point 5). The tasks are reported as "duplicates" even when they are unrelated. This is the only issue that loses user data.
2. **`--file` must come before the subcommand** (`todo list --file x` -> exit 2), and **the README is empty**. Together these are the most likely things to trip a new user.
3. **Tracebacks on edge inputs:** `serve --port 99999` (OverflowError) and `export` with a store task missing `created` (KeyError). Both bypass the otherwise consistent `error: ...` / exit 1 handling.
4. **`~` is not expanded** in a `TaskStore(path)` / `TODO_FILE` value. A literal `./~/` directory gets created instead.
5. Minor: there is no CLI way to edit due/priority after creation; `GET /tasks` ignores `status`/`sort` query parameters; CSV headers are case-sensitive; "1 duplicates" pluralisation.
