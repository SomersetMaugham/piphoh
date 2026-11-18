# todo-app

A small task manager with a command-line interface, a local REST API and CSV export/import.

## Requirements

- Python 3.10 or newer.
- Standard library only: there is nothing to install and no `pip install` step.
- Run every command from the repository root as `python -m todo ...`. If you run it from somewhere else,
  set `PYTHONPATH` to the repository root.

## Quick start

```sh
python -m todo --version
python -m todo add "Buy milk"
python -m todo add "Write report" --due 2026-12-01 --priority high
python -m todo list
python -m todo done 1
python -m todo list --status open --sort due
```

`list` prints one line per task. `[x]` marks a done task. A due date or a non-default priority is shown
after the title:

```text
1 [x] Buy milk
2 [ ] Write report (due 2026-12-01, priority high)
```

## Store file

Tasks are kept in a JSON file. The CLI and the REST server pick the file in this order:

1. `--file PATH`. It may come before or after the subcommand.
2. The `TODO_FILE` environment variable.
3. `~/.todo.json`.

`~` is expanded to your home directory, both in `--file` and in `TODO_FILE`. The file and its parent
directory are created when the first task is saved.

```sh
python -m todo --file work.json add "Prepare slides"
python -m todo list --file work.json
python -m todo --file ~/todo-work.json list
```

If the store file is not valid, CLI commands fail and leave the file unchanged. Bad JSON gives
`error: invalid JSON in <path>: ...`. A structural problem, such as a task with a missing or malformed
`created`, `due` or `priority`, gives `error: invalid store file <path>: <reason>`. The REST server keeps
running and answers each request with `500`.

## CLI commands

| Command | What it does |
|---|---|
| `add TITLE [--due YYYY-MM-DD] [--priority low\|normal\|high]` | Add a task. Prints `Added task <id>: <title>` |
| `list [--status open\|done] [--sort due\|priority\|created] [--json]` | List tasks, by id by default. `--json` prints a JSON array |
| `done ID` | Mark a task as done |
| `rm ID` | Delete a task. Ids are never reused |
| `edit ID [--title T] [--due YYYY-MM-DD \| --no-due] [--priority P]` | Change a task's title, due date and priority. Prints `Updated task <id>: <title>` |
| `export FILE` | Write all tasks to a CSV file (see below) |
| `import FILE` | Read tasks from a CSV file (see below) |
| `serve [--port N] [--host H]` | Run the REST API (see below) |
| `--version` | Print the version |

`--sort due` puts tasks without a due date last. `--sort priority` orders tasks high, normal, low.

```sh
python -m todo edit 2 --title "Write the report" --priority normal
python -m todo edit 2 --no-due
python -m todo list --json
python -m todo add "Temporary"
python -m todo rm 3
```

Exit codes: `0` on success. `1` on an error such as an unknown id or a bad due date; the CLI then prints
`error: <message>` to stderr. `2` on a usage error such as a missing argument or `--port 99999`:

```text
$ python -m todo done 42
error: task 42 not found
$ python -m todo edit 1
error: nothing to change (use --title, --due, --no-due or --priority)
```

## REST API

Start the server with `python -m todo serve --port 8000` (default port 8000, host 127.0.0.1; `--port 0`
picks a free port). It uses the same store file as the CLI and runs until Ctrl-C.

| Request | Body | Success | Errors |
|---|---|---|---|
| `GET /tasks` | none | `200`, JSON array of tasks | |
| `POST /tasks` | `{"title": ..., "due": ..., "priority": ...}`; only `title` is required | `201`, the task, `Location: /tasks/<id>` | `400` |
| `GET /tasks/<id>` | none | `200`, the task | `404` |
| `PATCH /tasks/<id>` | any of `title`, `done`, `due` (`null` clears it), `priority` | `200`, the updated task | `400`, `404` |
| `DELETE /tasks/<id>` | none | `204`, no body | `404` |

A task looks like this:
`{"id": 1, "title": "Buy milk", "done": false, "created": "2026-11-18T14:20:05Z", "due": null, "priority": "normal"}`.
Errors return `{"error": "<message>"}`. A wrong method gets `405` with an `Allow` header.

```text
$ python -m todo serve --port 8000
$ curl -s localhost:8000/tasks
$ curl -s -X POST localhost:8000/tasks -d '{"title": "Call Bob", "priority": "high"}'
$ curl -s -X PATCH localhost:8000/tasks/1 -d '{"done": true}'
$ curl -s -X DELETE localhost:8000/tasks/1
```

## CSV export/import

`export FILE` writes every task, overwriting `FILE`. The header is always:

```text
id,title,done,created,due,priority
```

`import FILE` reads a CSV with that header. Only the `title` column is required. Other columns may be left
out or left blank:

- A blank `id` gets a new id.
- A blank `done` means false.
- A blank `created` means now.
- A blank `priority` means normal.

Import is all-or-nothing. If any row is invalid, the command prints `error: FILE:<line>: <reason>` and
imports nothing. Existing tasks are never overwritten:

- A row whose id, `created` and title all match an existing task is the same task. It is skipped and
  counted as a duplicate. So re-importing your own export changes nothing.
- A row whose id is already used by a different task is imported under a new id, and the command prints a
  `Renumbered` line. No row is silently dropped.

```sh
python -m todo export tasks.csv
python -m todo import tasks.csv
python -m todo --file work.json import tasks.csv
```

The second command prints `Imported 0 tasks, skipped 2 duplicates`. The third merges into `work.json`,
which already has its own task 1:

```text
Imported 2 tasks, skipped 0 duplicates
Renumbered task 1 -> 3: id 1 is used by a different task
```

## Running tests

```sh
python -m unittest discover -s tests
```
