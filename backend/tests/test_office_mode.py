"""Step 13a: office mode (APP_ENV=office). No applicant portal, no emails to
applicants, every application entered by Records as a walk-in, staff only
from OFFICE_NETWORK, and no demo data."""

import pytest
from sqlalchemy import func, select

from app import demo_seed, dev_seed
from app.core.config import Settings, settings
from app.core.identity.models import PasswordLink
from app.core.notifications.models import Notification
from app.core.workflow import service as workflow
from app.modules.etls import service as etls
from tests.support import (
    TEST_PASSWORD,
    facility_letter_form,
    move,
    portal_headers,
    upload_required,
)

pytestmark = pytest.mark.anyio

OFFICE_NET = "10.9.0.0/16"


@pytest.fixture
def office(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "office")
    monkeypatch.setattr(settings, "office_network", OFFICE_NET)
    monkeypatch.setattr(settings, "staff_ip_allowlist_enabled", None)  # the default: on outside development
    monkeypatch.setattr(settings, "staff_ip_allowlist", "")


def _settings(**changes) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://x", jwt_secret="x" * 32, app_env="office",
        office_network=OFFICE_NET, staff_portal_key="k" * 40, mfa_secret_key="m" * 40, _env_file=None,
    )
    return Settings(**{**base, **changes})


def test_an_office_server_wont_start_half_configured():
    assert _settings().startup_problems() == []
    assert any("OFFICE_NETWORK" in p for p in _settings(office_network="").startup_problems())
    assert any("STAFF_PORTAL_KEY" in p for p in _settings(staff_portal_key=None).startup_problems())
    # The published dev key isn't a key outside development.
    assert any("STAFF_PORTAL_KEY" in p for p in _settings(staff_portal_key="dev-" + "k" * 40).startup_problems())
    assert any("MFA_SECRET_KEY" in p for p in _settings(mfa_secret_key=None).startup_problems())
    # Production and development don't need OFFICE_NETWORK.
    assert _settings(app_env="production", office_network="").startup_problems() == []


def test_staff_may_work_from_the_office_network_unless_a_list_is_given():
    assert [str(n) for n in _settings().staff_networks()] == [OFFICE_NET]
    assert [str(n) for n in _settings(staff_ip_allowlist="10.9.4.0/24").staff_networks()] == ["10.9.4.0/24"]
    assert _settings().staff_ip_check_on() is True


async def test_staff_sign_in_from_the_office_network_only(client, make_user, office):
    await make_user("officer", email="clerk@test.gm")
    body = {"email": "clerk@test.gm", "password": TEST_PASSWORD}
    inside = await client.post("/auth/login", json=body, headers=portal_headers("staff", ip="10.9.3.7"))
    assert inside.status_code == 200 and inside.json()["next"] == "set_up"
    outside = await client.post("/auth/login", json=body, headers=portal_headers("staff", ip="10.10.0.1"))
    assert outside.status_code == 403


async def test_there_is_no_applicant_portal(client, make_user, auth_headers, office):
    applicant = await make_user("applicant", email="importer@test.gm")
    login = await client.post(
        "/auth/login", json={"email": "importer@test.gm", "password": TEST_PASSWORD}, headers=portal_headers("applicant")
    )
    assert login.status_code == 401
    assert (await client.get("/auth/me", headers=await auth_headers(applicant))).status_code == 403
    link = await client.post("/auth/set-password", json={"token": "x" * 40, "password": "a long new password"})
    assert link.status_code == 404


async def test_applications_are_entered_by_records_only(db_session, make_user, office):
    applicant = await make_user("applicant")
    with pytest.raises(workflow.NotPermitted, match="entered by Records"):
        await etls.create_draft(db_session, actor=applicant, form=facility_letter_form())
    with pytest.raises(workflow.NotPermitted, match="entered by Records"):
        await workflow.start_case(db_session, workflow_code="etls_application", actor=applicant)


async def test_a_walk_in_gets_no_link_and_no_emails(act, people, db_session, office, monkeypatch):
    # The network check has its own tests; here, only links and emails.
    monkeypatch.setattr(settings, "staff_ip_allowlist_enabled", False)
    records = people["records_officer"]
    created = await act(
        records, "post", "/etls/facility-letters/walk-in",
        json={"applicant_email": "walkin@example.gm", "applicant_name": "Fatou Jallow", "form": facility_letter_form()},
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["case_id"]
    await upload_required(act, records, case_id)
    assert (await move(act, records, case_id, "submitted")).status_code == 200
    assert (await move(act, records, case_id, "originals_received")).status_code in (200, 409)

    # Only this case's rows: a few other tests commit theirs (the race tests).
    case = await workflow.get_case(db_session, case_id, records)
    links = select(func.count()).select_from(PasswordLink).where(PasswordLink.user_id == case.created_by)
    emails = select(func.count()).select_from(Notification).where(Notification.case_id == case_id)
    assert await db_session.scalar(links) == 0
    assert await db_session.scalar(emails) == 0


@pytest.mark.parametrize("seed", [dev_seed.main, demo_seed.main], ids=["dev_seed", "demo_seed"])
def test_demo_data_cant_be_loaded_in_the_office(monkeypatch, seed):
    monkeypatch.setattr(settings, "app_env", "office")
    with pytest.raises(SystemExit, match="Refusing"):
        seed()
