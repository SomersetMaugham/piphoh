"""Command-line dispatch for the todo application.

Later slices plug in by appending a dotted module name to COMMAND_MODULES;
each such module must define ``register(subparsers)``.
"""

import argparse
import importlib
import sys

from todo import __version__
from todo.errors import TodoError

COMMAND_MODULES: list[str] = ["todo.commands", "todo.server", "todo.csvio"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo")
    parser.add_argument(
        "--version", action="version", version=f"todo {__version__}"
    )
    parser.add_argument(
        "--file", metavar="PATH", default=None,
        help="task store file (default: $TODO_FILE or ~/.todo.json)",
    )
    subparsers = parser.add_subparsers(dest="command")
    for dotted in COMMAND_MODULES:
        importlib.import_module(dotted).register(subparsers)
    # Accept --file after the subcommand too, for every command (incl. ones
    # registered later). SUPPRESS keeps the top-level value unless given here,
    # so the occurrence after the subcommand wins.
    unique = {id(sub): sub for sub in subparsers.choices.values()}  # aliases share a parser
    for sub in unique.values():
        sub.add_argument(
            "--file", metavar="PATH", default=argparse.SUPPRESS,
            help="task store file (same as the global --file)",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.error("a command is required")  # argparse exits with code 2
    func = getattr(args, "func", None)
    if func is not None:
        try:
            return func(args)
        except TodoError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            return 130
        except Exception as exc:  # last resort: never show a traceback
            print(f"error: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    parser.error(f"command {args.command!r} has no handler")
    return 2  # unreachable; parser.error exits
