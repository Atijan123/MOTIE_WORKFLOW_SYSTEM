"""Constants and helpers shared by tests. (Fixtures live in conftest.py; pytest finds those itself.)"""

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


async def move(act, user, case_id, to_status, comment=None):
    """Ask the API to move a case; returns the response, whatever its status."""
    return await act(
        user, "post", f"/cases/{case_id}/status", json={"to_status": to_status, "comment": comment}
    )


def facility_letter_form(**changes) -> dict:
    """A valid ETLS facility letter form (JSON body); pass changes to vary it."""
    form = {
        "importer_name": "Kombo Building Supplies Ltd",
        "importer_address": "12 Kairaba Avenue, Serrekunda",
        "product": "Roofing sheets",
        "quantity": "1200.5",
        "unit": "tonnes",
        "exporter_name": "Dakar Steel SA",
        "exporter_country": "Senegal",
        "exporter_etls_approval_number": "SN-ETLS-0091",
        "product_approval_numbers": ["SN-PA-2025-011"],
        "certificate_of_origin_numbers": ["SN-CO-2026-0042"],
    }
    form.update(changes)
    return form


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
