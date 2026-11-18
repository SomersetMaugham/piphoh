"""Todo application package."""

__version__ = "0.1.0"

from todo.errors import StoreError, TaskNotFound, TodoError, ValidationError  # noqa: E402
from todo.store import TaskStore  # noqa: E402

__all__ = [
    "__version__",
    "TaskStore",
    "TodoError",
    "TaskNotFound",
    "ValidationError",
    "StoreError",
]
