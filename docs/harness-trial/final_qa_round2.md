# Final QA, round 2 (independent acceptance pass)

Scope: PRD `.harness/brief.md` points 1-11 and `README.md`, branch `harness/integration`.
Environment: Python 3.13.18, Linux, run as root. Every run used `PYTHONDONTWRITEBYTECODE=1`, a temp `HOME`,
`TODO_FILE` unset, and temp store/CSV files. The real `~/.todo.json` was never created or touched. All servers were
stopped with SIGINT (exit 0). `git status` was clean afterwards (only the ignored `.harness/`).

**Overall verdict: ACCEPT, with caveats.** All 11 PRD points pass or mostly pass. I saw no tracebacks, and no data
was lost in single-user use. Two caveats matter: concurrent writers lose data silently, and re-importing a CSV that
was renumbered on its first import duplicates those rows every time (see "Most important issues").

---

## 1. Library API (add/list/complete/delete, JSON persistence, default `~/.todo.json`) - PASS

Evidence (`from todo import TaskStore, ...`, store in a temp dir):
```
s.add("Buy milk")      -> {'id': 1, 'title': 'Buy milk', 'done': False, 'created': '2026-11-18T08:50:44Z', 'due': None, 'priority': 'normal'}
s.complete(1)          -> done True;  s.list(status="open") -> [task 2]
s.delete(2); s.add("Third") -> id 3 (id not reused)
s.get(99)              -> TaskNotFound task 99 not found
s.add("")              -> ValidationError title must not be empty
s.update(1)            -> ValidationError no fields to update
TaskStore().path       -> $HOME/.todo.json ;  TODO_FILE="~/env.json" -> $HOME/env.json
```
The file on disk is `{"version": 1, "next_id": 4, "tasks": [...]}`, pretty-printed. Saves are atomic (temp file + `os.replace`).
Gaps: the README does not document the library API. PRD 11 does not ask for it.

## 2. CLI add/list/done/rm/--version, exit codes, clear errors - PASS

```
$ todo --version            -> todo 0.1.0                      [exit 0]
$ todo add "Buy milk"       -> Added task 1: Buy milk          [exit 0]
$ todo done 1 / rm 3        -> Completed task 1 / Deleted task 3: Low thing [0]
$ todo done 42 / rm 42      -> error: task 42 not found        [exit 1]
$ todo done abc             -> usage ... invalid int value: 'abc' [exit 2]
$ todo add                  -> usage ... required: title        [exit 2]
$ todo                      -> usage ... a command is required  [exit 2]
$ todo add "   "            -> error: title must not be empty   [exit 1]
$ todo done -1 / done 0     -> error: task -1 not found / task 0 not found [1]
$ todo rm 99999999999999999999999 -> error: task ... not found [1]
```
`rm` then `add` gives a new id (4, not 3). `list` output matches the README format (`2 [ ] Write report (due 2026-12-01, priority high)`).
Gaps: `done` on a task that is already done prints "Completed" again (harmless). Running from outside the repo gives
`No module named todo`. The README says this and tells you to set `PYTHONPATH`.

## 3. Due date / priority, `--status`, `--sort` - PASS

```
$ todo add "Write report" --due 2026-12-01 --priority high ; add "Low thing" --priority low --due 2026-11-20
$ todo list --status open --sort due -> 3 (2026-11-20), 2 (2026-12-01)
$ todo list --sort priority          -> 2 high, 1 normal, 3 low
$ todo list --sort created / --status done / --json  -> correct
$ todo add x --due 2026-13-01  -> error: due is not a valid calendar date: '2026-13-01' [1]
$ todo add x --due 12/01/2026  -> error: due must be a date in YYYY-MM-DD format, got '12/01/2026' [1]
$ todo add x --priority urgent -> argparse invalid choice [2]
$ todo list --status foo       -> argparse invalid choice [2]
```
A legacy record with no `due`/`priority` lists and sorts fine; the defaults are filled in.

## 4. REST API (`serve --port N`) - PASS (minor gaps)

Live server (`serve --port 0`) tested with curl:
```
GET  /tasks                         200 JSON array
POST /tasks {"title":"Call Bob","priority":"high"}  201 + Location: /tasks/2
POST {"priority":"high"}            400 {"error": "missing field: title"}
POST {"title":""} / bad due / {"done":true} / "not json" / [1] / no body   all 400 with a JSON error
GET  /tasks/2  200 ; /tasks/99 404 "task 99 not found" ; /tasks/abc, /tasks/-1, /, /other  404
GET  /tasks/2?x=1 and /tasks/2/     200
PATCH {"done":true} 200 ; {"due":null,"title":"Renamed"} 200 (due cleared)
PATCH {"done":"yes"}/{"priority":null}/{"id":9}/{} 400 ; /tasks/99 404 ; garbage body 400
DELETE /tasks/1 204 (empty) ; again 404
PUT /tasks/2 405 Allow: GET, PATCH, DELETE ; DELETE /tasks 405 Allow: GET, POST
Store corrupted while serving -> 500 {"error": "invalid JSON in ..."}; server keeps running and recovers once the file is fixed
CLI add while serving -> visible through GET (shared store)
50 concurrent POSTs through the server -> 50 tasks, 50 unique ids
A client that stalls mid-body does not block other requests (threaded)
Ctrl-C (SIGINT) -> clean exit 0
```
Gaps:
- `HEAD /tasks` returns `501` with an HTML body from the stdlib. The README says "A wrong method gets 405 with an Allow header".
- `POST` accepts `"priority": null` (treated as normal), but `PATCH` rejects it with `got None`. This is inconsistent but documented nowhere.
- `serve --host ""` binds to `0.0.0.0`, all interfaces. The user has to ask for this explicitly; noted only.

## 5. CSV export/import - PARTIAL (works; repeat-import duplication)

```
$ todo export tasks.csv  -> Exported 2 tasks to ...; header id,title,done,created,due,priority; commas/quotes escaped correctly
$ todo import tasks.csv (same store, twice) -> Imported 0 tasks, skipped 2 duplicates   (both times)
$ todo --file work.json import tasks.csv   (work.json has its own task 1)
  Imported 2 tasks, skipped 0 duplicates
  Renumbered task 1 -> 3: id 1 is used by a different task        <- matches README exactly
$ todo --file work.json import tasks.csv   (SECOND time)
  Imported 1 tasks, skipped 1 duplicates
  Renumbered task 1 -> 4: id 1 is used by a different task        <- "Buy milk" now exists as tasks 3 AND 4
```
Other checks:
- A title-only CSV imports with new ids.
- `TRUE`/`0` are accepted for `done`, and a UTF-8 BOM is handled.
- All-or-nothing holds: a bad row on line 3 gives `error: FILE:3: due is not a valid calendar date` and nothing is
  imported. The same happens for an unknown column, a missing `title` column, a blank title, a bad priority, id
  `-3`/`abc`, too many fields, a bad `created`, an empty file, non-UTF-8 input, a missing file and a directory. Each
  gives a clear `error:` and exit 1.
- `export` into a missing directory or onto a directory gives a clear `error:` and exit 1.

Gaps:
- **Repeat import duplicates renumbered rows.** Importing the same foreign file N times adds N copies of every row
  that was renumbered. The duplicate check only compares a row with the task that holds the *same id*. It does not
  match the earlier renumbered copy, even though `created` and `title` are identical. Re-importing your own export is a
  no-op, which is what PRD 7 literally requires. But a user who repeats a merge, or imports a blank-id CSV twice
  (which also duplicates), piles up duplicates with no warning.
- An edited task (same id and `created`, new title) does not count as "the same task". Re-importing an old export
  after `edit --title` adds the old version as a new task each time. This is defensible as "never lose data", but it
  surprises users.
- Import reuses ids of deleted tasks. After `rm 2` and `rm 3`, importing a CSV with ids 2 and 3 puts them back under 2
  and 3. This contradicts the README's "Ids are never reused" (stated under `rm`). It is minor.
- `"unterminated` (an unclosed quote) is imported leniently as the title `unterminated`, with no error.
- Grammar: "Imported 1 tasks"; and with two CSV rows of the same id: "Renumbered task 7 -> 55", "Renumbered task 7 -> 56".
- A quoted `~` in an export/import path (`export '~/out.csv'`) is not expanded: `error: cannot write ~/out.csv`.
  PRD 9 only covers store paths; the shell expands unquoted `~`.

## 6. Tests - PASS

```
$ python -m unittest discover -s tests
Ran 267 tests in 104.895s
OK (skipped=1)
```

## 7. CSV import never silently loses data; re-importing own export is a no-op - PASS

Shown under 5: colliding rows are renumbered, with one `Renumbered` line per row. Re-importing your own export prints
`Imported 0 tasks, skipped N duplicates`, both for a 2-task and a 4-task merged store, and the file is unchanged.
No row was dropped in any run. The caveat is the opposite failure: repeat imports *duplicate* rows (see 5).

## 8. No tracebacks; `error: <msg>` and non-zero exit - PASS (one confusing message)

```
serve --port 99999 | -1 | abc | 8000.5 | "" | 1e3 -> "todo serve: error: argument --port: port must be an integer from 0 to 65535, got '99999'" [exit 2]
serve, port already in use   -> error: cannot listen on 127.0.0.1:42663: Address already in use [1]
serve --host bogus.invalid   -> error: cannot listen on bogus.invalid:0: Name or service not known [1]
store: bad JSON / empty file  -> error: invalid JSON in <path>: Expecting value ... [1]
store: task without created   -> error: invalid store file <path>: task 1 has invalid 'created' [1]  (list, done, export)
store: bad due/priority, string id, duplicate ids, no next_id, next_id 1e999/NaN, top-level [], tasks:[1], title null
                              -> error: invalid store file <path>: <reason> [1]
store is a directory          -> error: cannot read <path>: Is a directory [1]
unwritable parent             -> error: cannot write /proc/nope/x.json: No such file or directory [1]
```
In every malformed-store case the file was byte-for-byte unchanged afterwards.
Gaps:
- A store file that is not UTF-8 (bytes `\xff\xfe`) gives
  `error: unexpected UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff ...`. There is no traceback, but it
  comes from the last-resort handler and does not use the README's "invalid JSON in <path>" form.
- The port error carries an argparse usage line and the `todo serve:` prefix, and exits 2 instead of a plain
  `error:`. The README documents this, so it is acceptable.
- `--file ""` gives `error: cannot read .: Is a directory`, which is slightly cryptic.

## 9. `~` expansion (`--file`, `TODO_FILE`); `--file` after the subcommand - PASS

```
$ todo --file '~/work.json' list            -> uses $HOME/work.json
$ todo list --file '~/sub/dir/w2.json'; add ... -> $HOME/sub/dir/w2.json created with parents
$ TODO_FILE='~/env.json' todo add "from env" -> $HOME/env.json
$ TODO_FILE=... todo list --file ~/sub/dir/w2.json -> --file wins over TODO_FILE
$ todo --file a.json list --file ~/work.json -> the later --file wins; a.json not created
$ edit/done/rm/export with --file after the subcommand (incl. --file=~/work.json) -> all work
```
No literal `./~` directory was ever created.

## 10. `edit <id> [--title] [--due|--no-due] [--priority]` - PASS

```
$ todo edit 2 --title "Write the report" --priority normal -> Updated task 2: Write the report [0]
$ todo edit 2 --no-due / --due 2027-01-05                  -> [0]; list shows "(due 2027-01-05)"
$ todo edit 2 --due 2027-02-30 -> error: due is not a valid calendar date [1]
$ todo edit 2                  -> error: nothing to change (use --title, --due, --no-due or --priority) [1]
$ todo edit 99 --title y       -> error: task 99 not found [1]
$ todo edit 2 --due X --no-due -> argparse: not allowed with argument --due [2]
$ todo edit 2 --title ""       -> error: title must not be empty [1]
```

## 11. README documents CLI, REST API and CSV - PASS

Every README example I ran matched its documented output: the quick start, the `list` format, the error examples,
the curl examples, the CSV merge example and the exit-code table. One exception: the README says a wrong method gets
405, and HEAD gets 501 (see 4).

---

## Most important issues

1. **Silent data loss with concurrent writers (Medium-High).** There is no cross-process file locking. Each command
   reads the store, changes it and writes it back. Two runs showed this:
   - 20 parallel `todo add` processes all exited 0 and printed `Added task N`, but only 11 tasks were stored
     (`next_id` 12).
   - 20 CLI adds plus 20 REST POSTs against a running `serve` kept only 26 of 40 tasks.

   The README invites using the CLI and the server on the same store ("It uses the same store file as the CLI"). The
   PRD does not mention concurrency, but this is real data loss with a success message.
2. **Repeated CSV imports duplicate tasks (Medium).** After a merge renumbers a row, importing the same file again
   adds another copy each time. The same happens for blank-id CSVs and for re-importing an export after an edit.
   PRD 7 is literally met (own export is a no-op, nothing dropped), but "import the same file twice" is not
   idempotent for merged files.
3. **Import can reuse ids of deleted tasks (Low).** This contradicts the README's "Ids are never reused".
4. **`HEAD` gets 501 with an HTML body instead of 405 with JSON and `Allow` (Low).** This is a README mismatch.
5. **A non-UTF-8 store gives `error: unexpected UnicodeDecodeError: ...` (Low).** There is no traceback, but the
   message is unpolished.
6. **Minor polish (Low):**
   - "Imported 1 tasks".
   - POST and PATCH disagree on `"priority": null`.
   - An unclosed CSV quote is accepted silently.
   - A quoted `~` is not expanded in CSV paths.
