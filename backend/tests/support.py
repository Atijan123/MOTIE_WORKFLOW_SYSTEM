"""Constants and helpers shared by tests. (Fixtures live in conftest.py; pytest finds those itself.)"""

TEST_PASSWORD = "test password 123"


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
