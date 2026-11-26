"""Step 13e: the staff home page warns when the office server's last backup
is more than 2 days old (app/api/backup_status.py)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.api.backup_status import backup_status
from app.core.config import settings

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def office(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_env", "office")
    monkeypatch.setattr(settings, "staff_ip_allowlist_enabled", False)  # the network check has its own tests
    status_file = tmp_path / "last-success"
    monkeypatch.setattr(settings, "backup_status_file", str(status_file))
    return status_file


def test_a_recent_backup_gives_no_warning(office):
    office.write_text("2026-11-25T02:00:12Z\n")
    status = backup_status(NOW)
    assert status.warning is None and status.last_backup_at == datetime(2026, 11, 25, 2, 0, 12, tzinfo=timezone.utc)


def test_a_backup_over_two_days_old_is_warned_about(office):
    office.write_text("2026-11-23T02:00:00Z")
    assert backup_status(NOW).warning == (
        "The last backup was 3 days ago. Check the backup drive, and tell the system administrator."
    )
    # Exactly two days is still fine.
    office.write_text((NOW - timedelta(days=2)).isoformat())
    assert backup_status(NOW).warning is None


@pytest.mark.parametrize("content", [None, "", "not a date"], ids=["no file", "empty", "garbage"])
def test_no_readable_backup_is_warned_about(office, content):
    # No file: no backup yet, or the drive isn't plugged in.
    if content is not None:
        office.write_text(content)
    assert backup_status(NOW).warning.startswith("No backup can be found.")


def test_only_office_servers_have_backups_to_check(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    assert backup_status(NOW).checked is False


async def test_staff_see_it_applicants_dont(client, make_user, auth_headers, office):
    office.write_text("2026-11-01T02:00:00Z")
    officer = await make_user("officer")
    seen = await client.get("/system/backup-status", headers=await auth_headers(officer))
    assert seen.status_code == 200 and seen.json()["warning"].startswith("The last backup was")
