"""Is the office server's backup recent? (step 13e)

The nightly backup (office/backup/backup.sh) writes the time of its last
success to `last-success` on the backup drive. The API sees that drive
read-only, and the staff home page asks here whether to show a warning.
Only office mode has backups; elsewhere the answer is "not checked".
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import settings
from app.core.identity.deps import get_current_user
from app.core.identity.models import User

router = APIRouter(prefix="/system", tags=["system"])


class BackupStatus(BaseModel):
    checked: bool  # False except in office mode
    last_backup_at: datetime | None
    warning: str | None  # shown on the staff home page when set


def backup_status(now: datetime | None = None) -> BackupStatus:
    if settings.app_env != "office":
        return BackupStatus(checked=False, last_backup_at=None, warning=None)
    now = now or datetime.now(timezone.utc)
    try:
        text = Path(settings.backup_status_file).read_text(encoding="utf-8").strip()
        last = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (OSError, ValueError):
        # No file: no backup yet, or the drive isn't plugged in or mounted.
        return BackupStatus(
            checked=True,
            last_backup_at=None,
            warning="No backup can be found. Check the backup drive is plugged in, and tell the system administrator.",
        )
    if now - last > timedelta(days=settings.backup_warn_days):
        days = (now - last).days
        return BackupStatus(
            checked=True,
            last_backup_at=last,
            warning=f"The last backup was {days} days ago. Check the backup drive, and tell the system administrator.",
        )
    return BackupStatus(checked=True, last_backup_at=last, warning=None)


@router.get("/backup-status", response_model=BackupStatus)
async def get_backup_status(user: User = Depends(get_current_user)):
    if not user.is_staff:
        return BackupStatus(checked=False, last_backup_at=None, warning=None)
    return backup_status()
