"""Constants and helpers shared by tests. (Fixtures live in conftest.py; pytest finds those itself.)"""

from datetime import date, timedelta

from app.core.workflow.delegation import today

TEST_PASSWORD = "test password 123"

# Each person in the ETLS chain: their role and the post they hold.
STAFF = {
    "records_officer": ("records_officer", "records_officer"),
    "minister": ("minister", "minister"),
    "permanent_secretary": ("permanent_secretary", "permanent_secretary"),
    "dps": ("director", "dps_admin_finance"),  # there's no DPS role; any staff role will do
    "director": ("director", "director_of_industry"),
    "officer": ("officer", "industry_officer"),
    "desk": ("officer", "etls_desk_officer"),
}


async def open_case(act, applicant) -> dict:
    """Open an ETLS case as `applicant` through the API and return its JSON."""
    response = await act(applicant, "post", "/cases", json={"workflow": "etls_application"})
    assert response.status_code == 201, response.text
    return response.json()


async def move(act, user, case_id, to_status, comment=None, applicant_message=None):
    """Ask the API to move a case; returns the response, whatever its status."""
    return await act(
        user,
        "post",
        f"/cases/{case_id}/status",
        json={"to_status": to_status, "comment": comment, "applicant_message": applicant_message},
    )


def certificate(number: str, issued_on: date | None = None) -> dict:
    """One certificate of origin on the form; issued a month ago unless said otherwise."""
    return {"number": number, "issued_on": (issued_on or today() - timedelta(days=30)).isoformat()}


def facility_letter_form(*, certificate_of_origin_numbers: list[str] | None = None, **changes) -> dict:
    """A valid ETLS facility letter form (JSON body); pass changes to vary it.

    `certificate_of_origin_numbers=["A", "B"]` is a shortcut for certificates
    with those numbers, each issued a month ago."""
    form = {
        "importer_name": "Kombo Building Supplies Ltd",
        "importer_address": "12 Kairaba Avenue, Serrekunda",
        "product": "Roofing sheets",
        "hs_code": "7210.49",  # galvanised flat-rolled steel; not cement (2523)
        "quantity": "1200.5",
        "unit": "tonnes",
        "exporter_name": "Dakar Steel SA",
        "exporter_country": "Senegal",
        "exporter_etls_approval_number": "SN-ETLS-0091",
        "product_approval_numbers": ["SN-PA-2025-011"],
        "certificates_of_origin": [certificate(n) for n in certificate_of_origin_numbers or ["SN-CO-2026-0042"]],
    }
    form.update(changes)
    return form


# Documents a facility letter always needs (HS heading 2523, cement, also needs cement_receipt).
FACILITY_LETTER_DOCUMENTS = [
    "business_registration",
    "annual_returns_certificate",
    "certificate_of_origin",
    "invoice",
    "export_declaration",
]

# The smallest files our upload check accepts: it looks at the first bytes only.
PDF = b"%PDF-1.7\n% test file\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


async def upload(act, user, case_id, type_code, content=PDF, filename="scan.pdf"):
    """Upload `content` as the raw request body, as the frontend's fetch() will."""
    return await act(
        user,
        "post",
        f"/cases/{case_id}/documents/{type_code}",
        content=content,
        params={"filename": filename},
        headers_extra={"Content-Type": "application/octet-stream"},
    )


async def confirm_hs_code(act, people, case_id, hs_code="7210.49"):
    """The desk confirms the HS code, which its "Verify" move needs. Returns the response."""
    return await act(people["desk"], "post", f"/etls/facility-letters/{case_id}/hs-code", json={"hs_code": hs_code})


async def create_draft(act, applicant, **form) -> int:
    """Start a facility letter application (a draft) and return its case id."""
    response = await act(applicant, "post", "/etls/facility-letters", json=facility_letter_form(**form))
    assert response.status_code == 201, response.text
    return response.json()["case_id"]


async def upload_required(act, user, case_id) -> None:
    """Upload every document the case is known to need and doesn't have yet."""
    checklist = (await act(user, "get", f"/cases/{case_id}/documents")).json()
    for item in checklist:
        if item["missing"]:
            response = await upload(act, user, case_id, item["type"])
            assert response.status_code == 201, response.text


async def submit(act, user, case_id):
    """The applicant's "Submit" (or "Resubmit"). Returns the response."""
    return await move(act, user, case_id, "submitted")


async def submitted_case(act, people, **form) -> int:
    """A facility letter with its documents, submitted: waiting for Records."""
    case_id = await create_draft(act, people["applicant"], **form)
    await upload_required(act, people["applicant"], case_id)
    response = await submit(act, people["applicant"], case_id)
    assert response.status_code == 200, response.text
    return case_id


async def send_to_gra(act, people, case_id, dispatched_on=None, who="records_officer"):
    """Records' "Mark sent to GRA", with the dispatch date (today unless said). Returns the response."""
    return await act(
        people[who],
        "post",
        f"/etls/facility-letters/{case_id}/sent-to-gra",
        json={"dispatched_on": (dispatched_on or today()).isoformat()},
    )


# The ECOWAS ETLS list checks the desk ticks before Verify (0029).
ECOWAS_TICKS = ["ecowas_exporter_listed", "ecowas_product_covered"]


async def ready_to_verify(act, people, case_id, hs_code="7210.49"):
    """The desk confirms the HS code and ticks the ECOWAS list checks, which
    its Verify move needs. Returns the HS code response."""
    response = await confirm_hs_code(act, people, case_id, hs_code)
    for code in ECOWAS_TICKS:
        ticked = await act(people["desk"], "put", f"/cases/{case_id}/checklist/{code}", json={"ticked": True})
        assert ticked.status_code == 200, ticked.text
    return response


CEMENT = "2523.29"  # Portland cement: the cement receipt applies once the desk confirms it


async def verified_case(act, people, hs_code="7210.49", **form) -> int:
    """A facility letter the desk has verified, waiting for signature. With a
    cement `hs_code`, the cement receipt is uploaded once the code is confirmed."""
    case_id = await create_draft(act, people["applicant"], hs_code=hs_code, **form)
    await ready_for_records(act, people, case_id)
    response = await move(act, people["records_officer"], case_id, "originals_received")
    assert response.status_code == 200, response.text
    assert (await ready_to_verify(act, people, case_id, hs_code)).status_code == 200
    await upload_required(act, people["applicant"], case_id)  # the receipt, for cement
    response = await move(act, people["desk"], case_id, "verified")
    assert response.status_code == 200, response.text
    return case_id


async def record_absence(act, user, days=3):
    """`user` records their own absence from today. Returns the response."""
    return await act(
        user,
        "post",
        "/absences",
        json={"starts_on": today().isoformat(), "ends_on": (today() + timedelta(days=days - 1)).isoformat()},
    )


SIGNATORY_LIST = "director_absence"


async def add_signatory(act, admin, user):
    """`admin` (signatory_admin) puts `user` on the Director's-absence list. Returns the response."""
    return await act(admin, "post", f"/signatories/{SIGNATORY_LIST}/members", json={"user_id": user.id})


async def ready_for_records(act, people, case_id) -> None:
    """Upload every document the case needs and submit it (as the applicant),
    then have Records mark the original certificate of origin as seen, so
    Records may confirm."""
    await upload_required(act, people["applicant"], case_id)
    if (await act(people["applicant"], "get", f"/cases/{case_id}")).json()["status"]["editable"]:
        response = await submit(act, people["applicant"], case_id)
        assert response.status_code == 200, response.text
    checklist = (await act(people["records_officer"], "get", f"/cases/{case_id}/documents")).json()
    for item in checklist:
        if item["original_required"] and item["original_pending"] and item["documents"]:
            seen = await act(
                people["records_officer"],
                "post",
                f"/cases/{case_id}/documents/{item['documents'][0]['id']}/original-seen",
            )
            assert seen.status_code == 200, seen.text


# --- A made-up register of historical letters (step 11) ----------------------
# Every name and number here is invented. The real register is never used in tests.

HISTORY_IMPORTER = "Banjul Test Traders"  # filter on this: other tests commit live letters too
HISTORICAL_CERTIFICATE = "HX-CO-2025-0001"


def made_up_register(folder, **changes) -> "Path":
    """Write a small register with the real sheets and headings. Letter 1 is
    filed twice; letters 1 and 3 share a certificate; letter 4 has no readable
    date. `changes` replaces whole sheets (letters, goods, checks)."""
    from datetime import datetime

    from app.modules.etls.import_history import write_register

    letters = [
        {
            "Letter no.": 1, "Folio(s) in file": "3-4", "PDF page(s)": "File 2, p. 7", "Letter reference": "ADM/TEST/1",
            "Letter date": "16th October, 2025", "Importer": HISTORY_IMPORTER, "Importer address / cc": "1 Test Street, Banjul",
            "Goods (as in letter)": "Poultry feed and maize", "Category": "Feed", "Exporter": "Dakar Test SA",
            "Exporter country": "Senegal", "Exporter approval no. (as written)": "sn etls 1",
            "Exporter approval no. (standard)": "SN-ETLS-0001", "Product approval no(s).": "SN-PA-1",
            "Tariff code(s)": "2309.90", "Certificate of origin no(s).": f"{HISTORICAL_CERTIFICATE}; HX-CO-2025-0002",
            "No. of certificates": 2, "Bill of lading / container": "BL-1", "Signed by": "A. Test Director",
            "Signed as": "For: Permanent Secretary", "Check notes": "Folio 4 is faint",
            "Also filed at (second copy of this letter)": "File 5, p. 9 (folio 5)",
        },
        {
            "Letter no.": 3, "Folio(s) in file": "9", "Letter reference": "ADM/TEST/3",
            "Letter date": datetime(2026, 1, 20), "Importer": "  BANJUL TEST   TRADERS ",
            "Exporter": "Accra Test Ltd", "Exporter country": "Ghana",
            "Certificate of origin no(s).": "HX-CO-2025-0002", "Signed by": "B. Test Officer",
            "Signed as": "In the Director's absence",
        },
        {
            "Letter no.": 4, "Folio(s) in file": "11", "Letter reference": "ADM/TEST/4", "Letter date": "unclear",
            "Importer": HISTORY_IMPORTER, "Goods (as in letter)": "Cement", "Category": "Cement",
            "Certificate of origin no(s).": "HX-CO-2025-0004", "Signed by": "A. Test Director",
        },
        {
            # A cell that would run as a formula in Excel: the CSV must defuse it.
            "Letter no.": 5, "Letter reference": "ADM/TEST/5", "Letter date": "2026-02-03",
            "Importer": "=HYPERLINK(\"http://bad.test\") Banjul Test Traders",
        },
    ]
    goods = [
        {"Line no.": 1, "Letter no.": 1, "Product": "Poultry feed", "Category": "Feed", "Quantity": 1200, "Unit": "bags"},
        {"Line no.": 2, "Letter no.": 1, "Product": "Maize", "Category": "Feed", "Quantity": "10.5", "Unit": "tonnes"},
        {"Line no.": 3, "Letter no.": 3, "Product": "Poultry feed", "Category": "feed", "Quantity": "1,000", "Unit": "Bags"},
        {"Line no.": 4, "Letter no.": 4, "Product": "Cement", "Category": "Cement", "Quantity": "about 300", "Unit": "tonnes"},
    ]
    checks = [
        {"Check no.": 1, "Folio(s)": "4", "What looks wrong": "Date hard to read", "What to check": "Compare with the file"},
        {"Check no.": 2, "Letter reference": "ADM/TEST/3", "What looks wrong": "Importer in capitals"},
        {"Check no.": 3, "Letter reference": "ADM/NOWHERE", "What looks wrong": "Not in the file"},
    ]
    sheets = {"letters": letters, "goods": goods, "checks": checks, **changes}
    return write_register(folder / "made-up-register.xlsx", sheets["letters"], sheets["goods"], sheets["checks"])
