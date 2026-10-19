"""Fixtures shared by the tests in tests/core/."""

import pytest

# Each staff role in the ETLS chain, and the post its test user holds.
POSITION_FOR = {
    "records_officer": "records_officer",
    "minister": "minister",
    "permanent_secretary": "permanent_secretary",
    "director": "director_of_trade",
    "officer": "trade_officer",
}


@pytest.fixture
async def people(make_user):
    """One user per role in the ETLS chain, each holding the matching post."""
    users = {"applicant": await make_user("applicant")}
    for role, position in POSITION_FOR.items():
        users[role] = await make_user(role, positions=[position])
    return users


@pytest.fixture
def act(client, auth_headers):
    """Shortcut: `await act(user, "post", "/cases/1/status", json=...)`."""

    async def _act(user, method, url, **kwargs):
        return await getattr(client, method)(url, headers=auth_headers(user), **kwargs)

    return _act
