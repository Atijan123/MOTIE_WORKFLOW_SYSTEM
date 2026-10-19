"""Fixtures shared by the tests in tests/core/."""

import pytest

# Each person in the ETLS chain: their role and the post they hold.
STAFF = {
    "records_officer": ("records_officer", "records_officer"),
    "minister": ("minister", "minister"),
    "permanent_secretary": ("permanent_secretary", "permanent_secretary"),
    "dps": ("director", "dps_admin_finance"),  # there's no DPS role; any staff role will do
    "director": ("director", "director_of_industry"),
    "officer": ("officer", "industry_officer"),
}


@pytest.fixture
async def people(make_user):
    """The applicant plus one user per post in the ETLS chain."""
    users = {"applicant": await make_user("applicant")}
    for key, (role, position) in STAFF.items():
        users[key] = await make_user(role, positions=[position])
    return users


@pytest.fixture
def act(client, auth_headers):
    """Shortcut: `await act(user, "post", "/cases/1/status", json=...)`."""

    async def _act(user, method, url, **kwargs):
        return await getattr(client, method)(url, headers=auth_headers(user), **kwargs)

    return _act
