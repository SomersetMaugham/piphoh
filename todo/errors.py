"""Exception hierarchy for the todo application."""


class TodoError(Exception):
    """Base class for all todo errors; ``str(e)`` is a human-readable message."""


class TaskNotFound(TodoError):
    """Raised when a task id does not exist."""

    def __init__(self, task_id: int):
        self.task_id = task_id
        super().__init__(f"task {task_id} not found")


class ValidationError(TodoError, ValueError):
    """Raised for a bad title, unknown field or wrong field type."""


class StoreError(TodoError):
    """Raised when the store file is unreadable, invalid JSON or malformed."""
