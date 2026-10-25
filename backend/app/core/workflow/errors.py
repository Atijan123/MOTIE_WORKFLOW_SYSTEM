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


class InvalidAbsence(WorkflowError):
    """The absence breaks a rule (dates, or the person holds no post)."""


class AlreadyCancelled(WorkflowError):
    pass


class CaseBlocked(WorkflowError):
    """The case has an open blocking flag; someone must resolve it first."""


class AlreadyResolved(WorkflowError):
    pass


class InvalidDocument(WorkflowError):
    """The document isn't one this case takes, or is empty."""


class UploadTooLarge(WorkflowError):
    pass


class UnsupportedFileType(WorkflowError):
    pass


class CommentRequired(WorkflowError):
    """The move needs a written reason (or a message to the applicant), and none was given."""


class InvalidDate(WorkflowError):
    """A date given with a move breaks a rule (e.g. in the future)."""


class MessageNotExpected(WorkflowError):
    """A message to the applicant was given on a move that doesn't send one."""


class NotReady(WorkflowError):
    """The move is allowed, but one of its checks (e.g. documents complete) fails."""
