"""The registry file reference on the letter (SCREENS.md global rules): a dev
default, but on a real server signing waits until it's set."""

import pytest
from pydantic import ValidationError

from app.core.config import DEV_REGISTRY_REFERENCE, Settings, settings
from tests.support import move, ready_for_records, ready_to_verify, submitted_case

pytestmark = pytest.mark.anyio

NOT_SET = "the Ministry's registry file reference isn't set"


async def _verified(act, people) -> int:
    case_id = await submitted_case(act, people)
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    await ready_to_verify(act, people, case_id)
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    return case_id


async def _sign_action(act, people, case_id) -> dict:
    case = (await act(people["director"], "get", f"/cases/{case_id}")).json()
    [action] = [a for a in case["available_actions"] if a["to_status"] == "signed"]
    return action


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "facility_letter_reference_format", None)


async def test_in_production_signing_waits_for_the_setting(act, people, production):
    case_id = await _verified(act, people)
    [reason] = (await _sign_action(act, people, case_id))["blocked_by"]
    assert NOT_SET in reason and "FACILITY_LETTER_REFERENCE_FORMAT" in reason
    response = await move(act, people["director"], case_id, "signed")
    assert response.status_code == 409
    assert NOT_SET in response.json()["detail"]


async def test_in_production_signing_works_once_it_is_set(act, people, production, monkeypatch):
    monkeypatch.setattr(settings, "facility_letter_reference_format", "ADM 151/420/02")
    case_id = await _verified(act, people)
    assert (await _sign_action(act, people, case_id))["blocked_by"] == []
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200


async def test_the_preview_says_it_is_not_set(act, people, production):
    case_id = await _verified(act, people)
    response = await act(people["director"], "get", f"/etls/facility-letters/{case_id}/letter-preview.pdf")
    assert response.status_code == 200  # the PS can still read the letter


async def test_in_development_the_example_is_the_default(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "facility_letter_reference_format", None)
    assert settings.registry_reference_format() == DEV_REGISTRY_REFERENCE == "ADM 151/420/01/PART IV"
    monkeypatch.setattr(settings, "app_env", "production")
    assert settings.registry_reference_format() is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_setting_counts_as_not_set(blank):
    # docker-compose.yml passes FACILITY_LETTER_REFERENCE_FORMAT through even when .env leaves it out.
    assert Settings(facility_letter_reference_format=blank, app_env="production").registry_reference_format() is None


def test_a_bad_format_is_still_refused_at_startup():
    with pytest.raises(ValidationError):
        Settings(facility_letter_reference_format="{importer}")
