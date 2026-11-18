"""Core CLI commands: add, list, done, rm (registered via todo.cli.COMMAND_MODULES)."""

import json

from todo.store import TaskStore


def _store(args) -> TaskStore:
    return TaskStore(args.file)


def format_task(task: dict) -> str:
    mark = "x" if task.get("done") else " "
    return f"{task['id']} [{mark}] {task['title']}"


def cmd_add(args) -> int:
    task = _store(args).add(args.title)
    print(f"Added task {task['id']}: {task['title']}")
    return 0


def cmd_list(args) -> int:
    tasks = _store(args).list()
    if args.json:
        print(json.dumps(tasks))
    elif not tasks:
        print("No tasks.")
    else:
        for task in tasks:
            print(format_task(task))
    return 0


def cmd_done(args) -> int:
    task = _store(args).complete(args.id)
    print(f"Completed task {task['id']}: {task['title']}")
    return 0


def cmd_rm(args) -> int:
    task = _store(args).delete(args.id)
    print(f"Deleted task {task['id']}: {task['title']}")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("add", help="add a task")
    p.add_argument("title", help="task title")
    p.set_defaults(func=cmd_add)

    p = subparsers.add_parser("list", help="list tasks")
    p.add_argument("--json", action="store_true", help="output tasks as a JSON array")
    p.set_defaults(func=cmd_list)

    p = subparsers.add_parser("done", help="mark a task as done")
    p.add_argument("id", type=int, help="task id")
    p.set_defaults(func=cmd_done)

    p = subparsers.add_parser("rm", help="delete a task")
    p.add_argument("id", type=int, help="task id")
    p.set_defaults(func=cmd_rm)
