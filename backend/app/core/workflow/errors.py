"""Errors raised by the workflow engine and delegation code.

They are plain Python exceptions, so the code works from the CLI and tests too.
router.py turns each one into an HTTP status.
"""


class WorkflowError(Exception):
    """Base class; the API turns each subclass into an HTTP status (see router.py)."""


class NotFound(WorkflowError):
    pass


class NotPermitted(WorkflowError):
    pass


class TransitionNotAllowed(WorkflowError):
    pass


class InvalidDelegation(WorkflowError):
    """The delegation request breaks a rule (dates, length, delegating to yourself)."""


class AlreadyRevoked(WorkflowError):
    pass
