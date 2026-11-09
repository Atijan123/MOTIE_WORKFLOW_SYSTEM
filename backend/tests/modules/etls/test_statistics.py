"""S13: ETLS statistics over live and historical letters, the CSV, one
historical letter's page, and the duplicate check (S2) searching history.

Other tests commit live letters too (the race tests), so figures are checked
with the importer filter on the made-up importer, never as global totals."""

import csv
import io

import pytest
from sqlalchemy import select

from app.core.workflow.models import CaseFlag
from app.modules.etls.history_models import HistoricalLetter
from tests.support import (
    HISTORICAL_CERTIFICATE,
    HISTORY_IMPORTER,
    certificate,
    made_up_register,
    move,
    send_to_gra,
    submitted_case,
    verified_case,
)

pytestmark = pytest.mark.anyio

ONLY_OURS = {"importer": "banjul test"}


@pytest.fixture
async def history(import_history, tmp_path):
    return await import_history(made_up_register(tmp_path))


@pytest.fixture
async def viewer(make_user):
    return await make_user("officer", "stats_viewer")


async def _stats(act, user, **params) -> dict:
    response = await act(user, "get", "/etls/statistics", params={**ONLY_OURS, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _rows(figure) -> dict[str, int]:
    return {r["label"]: r["letters"] for r in figure["rows"]}


async def _live_letter(act, people, **form) -> int:
    """A live letter for our made-up importer, signed and sent to GRA."""
    case_id = await verified_case(act, people, importer_name=HISTORY_IMPORTER, **form)
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200
    assert (await send_to_gra(act, people, case_id)).status_code == 200
    return case_id


# --- Who may see it ------------------------------------------------------------


@pytest.mark.parametrize("who, allowed", [("director", True), ("viewer", True), ("desk", False), ("dps", False)])
async def test_the_director_and_stats_viewers_only(act, people, viewer, who, allowed):
    user = viewer if who == "viewer" else people[who]
    for url in ("/etls/statistics", "/etls/statistics/letters.csv"):
        assert (await act(user, "get", url)).status_code == (200 if allowed else 403)


# --- The figures -----------------------------------------------------------------


async def test_live_and_historical_together(act, people, viewer, history):
    await _live_letter(act, people, certificate_of_origin_numbers=["HX-CO-LIVE-1"])
    found = await _stats(act, viewer)

    # Letters 1, 3, 4, 5, and the live one.
    assert (found["letters"], found["historical"], found["live"], found["undated"]) == (5, 4, 1, 1)
    assert found["by_year"]["based_on"] == 4  # the undated one can't be placed
    assert "1 letter(s) with no readable date" in found["by_year"]["note"]
    years = _rows(found["by_year"])
    assert years["2025"] == 1 and years["2026"] >= 2  # + the live letter, dated today
    assert _rows(found["by_month"])["2025-10"] == 1

    # "BANJUL TEST TRADERS" and "Banjul Test Traders" are one importer.
    assert _rows(found["importers"])[HISTORY_IMPORTER] == 4
    assert found["importers"]["based_on"] == 5
    assert _rows(found["exporter_countries"]) == {"Senegal": 2, "Ghana": 1, "Not recorded": 2}
    signers = _rows(found["signatories"])
    assert signers["A. Test Director"] == 2 and signers["B. Test Officer"] == 1
    assert signers[people["director"].full_name] == 1  # the live letter's signer


async def test_quantities_never_add_different_units(act, people, viewer, history):
    found = await _stats(act, viewer)
    quantities = {(q["category"], q["unit"]): (q["total"], q["letters"]) for q in found["quantities"]["rows"]}
    # Feed in bags: 1200 + 1000 over two letters ("feed"/"Bags" written differently, same row).
    assert quantities[("Feed", "bags")] == ("2200.000", 2)
    assert quantities[("Feed", "tonnes")] == ("10.500", 1)  # never added to bags
    assert found["quantities"]["lines_without_quantity"] == 1  # "about 300"; letter 5 has no lines at all
    assert found["quantities"]["based_on"] == 2


async def test_certificates_used_more_than_once(act, people, viewer, history):
    found = await _stats(act, viewer)
    shared = {r["number"]: r["letters"] for r in found["shared_certificates"]["rows"]}
    # HX-CO-2025-0002 is on letters 1 and 3.
    assert len(shared["HX-CO-2025-0002"]) == 2
    assert HISTORICAL_CERTIFICATE not in shared  # only on letter 1
    assert found["shared_certificates"]["based_on"] == 3


async def test_the_date_range_leaves_out_undated_letters(act, people, viewer, history):
    found = await _stats(act, viewer, date_from="2025-10-01", date_to="2025-12-31")
    assert (found["letters"], found["undated"]) == (1, 0)
    assert (await act(viewer, "get", "/etls/statistics", params={"date_from": "2026-01-02", "date_to": "2026-01-01"})).status_code == 422


async def test_data_checks_the_import_could_not_link_are_listed(act, viewer, history):
    found = await _stats(act, viewer)
    assert [c["reference"] for c in found["unlinked_checks"]] == ["ADM/NOWHERE"]


# --- The CSV ---------------------------------------------------------------------


async def test_the_csv_is_the_filtered_table(act, people, viewer, history):
    response = await act(viewer, "get", "/etls/statistics/letters.csv", params={**ONLY_OURS, "date_from": "2025-01-01"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="etls-facility-letters-2025-01-01.csv"' in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0][:4] == ["Source", "Reference", "Letter no.", "Date"]
    assert [r[2] for r in rows[1:]] == ["1", "3", "5"]  # dated letters only, oldest first
    # A cell that would run as a formula in Excel starts with ' instead.
    formula = next(r for r in rows if r[2] == "5")[4]
    assert formula.startswith("'=HYPERLINK")


# --- One historical letter -------------------------------------------------------


async def test_a_historical_letter_page_shows_the_row_and_checks(act, people, history, db_session):
    first = await db_session.scalar(select(HistoricalLetter).where(HistoricalLetter.letter_no == 1))
    response = await act(people["desk"], "get", f"/etls/history/{first.id}")  # any staff
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["letter"]["exporter_approval_as_written"] == "sn etls 1"
    assert (page["letter"]["source_file"], page["letter"]["source_page"]) == ("File 2", 7)
    assert page["letter"]["also_filed_at"] == "File 5, p. 9 (folio 5)"
    assert page["certificates"] == [HISTORICAL_CERTIFICATE, "HX-CO-2025-0002"]
    assert [g["product"] for g in page["goods"]] == ["Poultry feed", "Maize"]
    assert [c["what_looks_wrong"] for c in page["checks"]] == ["Date hard to read"]

    assert (await act(people["applicant"], "get", f"/etls/history/{first.id}")).status_code == 403
    assert (await act(people["desk"], "get", "/etls/history/999999")).status_code == 404


# --- The duplicate check (S2) searches history -----------------------------------


async def test_a_certificate_on_a_historical_letter_flags_the_case(act, people, history, db_session):
    case_id = await submitted_case(act, people, certificates_of_origin=[certificate(HISTORICAL_CERTIFICATE.lower())])
    flag = await db_session.scalar(select(CaseFlag).where(CaseFlag.case_id == case_id))
    # Letter 2 is a copy of letter 1: one use, said once.
    assert flag.message == (
        "Certificate of origin number(s) HX-CO-2025-0001 used on historical letter ADM/TEST/1, "
        f"16th October, 2025, {HISTORY_IMPORTER}"
    )
    assert len(flag.details["historical_letter_ids"]["HX-CO-2025-0001"]) == 1

    [duplicate] = (await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/duplicates")).json()
    assert duplicate["other_cases"] == []
    [used] = duplicate["historical_letters"]
    assert (used["letter_no"], used["reference"], used["importer"]) == (1, "ADM/TEST/1", HISTORY_IMPORTER)
    assert used["described"].startswith("historical letter ADM/TEST/1, 16th October, 2025")


async def test_a_number_never_used_raises_no_flag(act, people, history, db_session):
    case_id = await submitted_case(act, people, certificates_of_origin=[certificate("HX-CO-NEW-1")])
    assert await db_session.scalar(select(CaseFlag.id).where(CaseFlag.case_id == case_id)) is None
