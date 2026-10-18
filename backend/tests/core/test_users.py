import pytest

from app.core.identity.security import verify_password
from app.core.identity.service import (
    UnknownRole,
    UserAlreadyExists,
    WeakPassword,
    create_user,
    get_user_by_email,
)

pytestmark = pytest.mark.anyio

GOOD_PASSWORD = "correct horse battery"


async def test_create_user_stores_a_hash_not_the_password(db_session):
    user = await create_user(
        db_session,
        email="Records@MOTIE.gov.gm ",
        full_name="Awa Jallow",
        password=GOOD_PASSWORD,
        role_codes=["records_officer"],
    )

    assert user.id is not None
    assert user.is_active is True
    assert user.email == "records@motie.gov.gm"
    assert user.role_codes == {"records_officer"}
    assert user.password_hash != GOOD_PASSWORD
    assert verify_password(GOOD_PASSWORD, user.password_hash)


async def test_lookup_by_email_ignores_case(db_session):
    await create_user(
        db_session, email="a@motie.gov.gm", full_name="A", password=GOOD_PASSWORD, role_codes=[]
    )
    assert await get_user_by_email(db_session, "A@Motie.gov.gm") is not None


async def test_user_can_have_several_roles(db_session):
    user = await create_user(
        db_session,
        email="dir@motie.gov.gm",
        full_name="D",
        password=GOOD_PASSWORD,
        role_codes=["director", "officer"],
    )
    assert user.role_codes == {"director", "officer"}


async def test_duplicate_email_is_refused(db_session):
    await create_user(
        db_session, email="a@motie.gov.gm", full_name="A", password=GOOD_PASSWORD, role_codes=[]
    )
    with pytest.raises(UserAlreadyExists):
        await create_user(
            db_session, email="A@motie.gov.gm", full_name="B", password=GOOD_PASSWORD, role_codes=[]
        )


async def test_unknown_role_is_refused(db_session):
    with pytest.raises(UnknownRole):
        await create_user(
            db_session,
            email="a@motie.gov.gm",
            full_name="A",
            password=GOOD_PASSWORD,
            role_codes=["king"],
        )


async def test_short_password_is_refused(db_session):
    with pytest.raises(WeakPassword):
        await create_user(
            db_session, email="a@motie.gov.gm", full_name="A", password="short", role_codes=[]
        )
