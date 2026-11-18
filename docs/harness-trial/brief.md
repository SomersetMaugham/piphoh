# PRD: todo-app (verbatim brief)

Build a small task manager in Python 3 using only the standard library.

1. A library API to add, list, complete and delete tasks. Tasks persist in a JSON file
   (path configurable; default `~/.todo.json`). Each task has an integer id, title,
   done flag, created timestamp.
2. A command-line interface: `python -m todo add "title"`, `list`, `done <id>`, `rm <id>`,
   `--version`. Exit code 0 on success, non-zero with a clear message on errors
   (e.g. unknown id).
3. Tasks can have an optional due date (YYYY-MM-DD) and priority (low/normal/high).
   `list` can filter by `--status open|done` and sort by `--sort due|priority|created`.
4. A local REST API (`python -m todo serve --port N`) exposing GET/POST /tasks,
   GET/PATCH/DELETE /tasks/<id>, returning JSON with proper status codes (201, 404, 400).
5. Export to and import from CSV (`export file.csv`, `import file.csv`).
6. Tests runnable with `python -m unittest discover -s tests`.

## Follow-up requirements (from final independent QA, approved by the user 2026-11-18)
7. CSV import must never silently lose data: a row whose id collides with a *different* existing task must not be dropped.
   Re-importing the store's own export must still be a no-op.
8. Errors must never print a Python traceback: invalid `serve --port` values, malformed task records in the store file
   (e.g. a task without `created`), and similar cases print `error: <msg>` and exit non-zero.
9. `~` in store paths (argument or TODO_FILE) expands to the home directory. `--file` is accepted after the subcommand too.
10. The CLI can edit a task's title, due date and priority (`edit <id> [--title T] [--due D|--no-due] [--priority P]`).
11. README documents installation-free usage of the CLI, REST API and CSV commands.
