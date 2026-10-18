"""Import every model module here.

A table class only registers itself on Base.metadata when its module is imported.
Alembic imports this file so it can see all tables.
"""

from app.core.audit import models as audit_models  # noqa: F401
from app.core.identity import models as identity_models  # noqa: F401
from app.core.workflow import models as workflow_models  # noqa: F401
