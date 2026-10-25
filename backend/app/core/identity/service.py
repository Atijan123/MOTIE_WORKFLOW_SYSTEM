"""Business logic for users. Endpoints and the CLI call these; they never write SQL themselves."""

from functools import cache

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.identity.models import Position, Role, User, position_holders
from app.core.identity.security import hash_password, verify_password

AUDIT_ENTITY = "user"

# NIST SP 800-63B recommends length over complexity rules. 12 is a common floor
# for staff accounts.
MIN_PASSWORD_LENGTH = 12


class UserAlreadyExists(Exception):
    pass


class UnknownRole(Exception):
    pass


class WeakPassword(Exception):
    pass


class UnknownPosition(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == normalize_email(email)))


def check_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")


async def create_user(
    session: AsyncSession,
    *,
    email: str | None,
    full_name: str,
    password: str | None,
    role_codes: list[str],
) -> User:
    """`password=None` makes an account nobody can log in to until a password
    is set (a walk-in applicant, see password_links.py). `email=None` only for
    a walk-in applicant who has none."""
    email = normalize_email(email) if email is not None else None
    if password is not None:
        check_password_strength(password)
    if email is not None and await get_user_by_email(session, email):
        raise UserAlreadyExists(f"A user with email {email} already exists.")

    roles = (await session.scalars(select(Role).where(Role.code.in_(role_codes)))).all()
    missing = set(role_codes) - {role.code for role in roles}
    if missing:
        raise UnknownRole(f"Unknown role(s): {', '.join(sorted(missing))}")

    user = User(
        email=email,
        full_name=full_name.strip(),
        password_hash=hash_password(password) if password is not None else None,
        roles=list(roles),
    )
    session.add(user)
    await session.commit()
    # A new user holds no posts, but `positions` was never loaded (selectin only
    # runs when a user is read from the database), and async code can't load it
    # later on first touch. Load it now so callers get a complete user.
    await session.refresh(user, ["positions"])
    return user


@cache
def _dummy_hash() -> str:
    return hash_password("placeholder password used only for timing")


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    """Return the user if the email and password are right and the account is active.

    Every failure returns None, so the caller can't tell *why* it failed. That
    stops an attacker learning which emails have accounts.
    """
    user = await get_user_by_email(session, email)
    if user is None or user.password_hash is None:
        # Still run a hash check, so "no such email" (or "no password set
        # yet") takes as long as "wrong password". Otherwise response time
        # would reveal which emails exist.
        verify_password(password, _dummy_hash())
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


async def get_position(session: AsyncSession, code: str) -> Position:
    position = await session.scalar(select(Position).where(Position.code == code))
    if position is None:
        raise UnknownPosition(f"Unknown position: {code}")
    return position


async def assign_position(
    session: AsyncSession, *, user: User, position_code: str, actor: User | None
) -> bool:
    """Make `user` a holder of the position. Returns False if they already held it.

    `actor` is who made the change (None when done from the CLI). Assigning a
    post gives someone approval rights, so every change is audited.
    """
    position = await get_position(session, position_code)
    # ON CONFLICT DO NOTHING + RETURNING: if the row already exists (even one
    # added a moment ago by someone else), nothing is inserted and nothing comes
    # back, so we don't write an audit row for a change that didn't happen.
    added = await session.scalar(
        insert(position_holders)
        .values(position_id=position.id, user_id=user.id)
        .on_conflict_do_nothing()
        .returning(position_holders.c.position_id)
    )
    if added is None:
        return False
    record_event(
        session,
        actor=actor,
        action="position.assigned",
        entity_type=AUDIT_ENTITY,
        entity_id=user.id,
        details={"position": position.code},
    )
    await session.commit()
    await session.refresh(user, ["positions"])
    return True


async def remove_position(
    session: AsyncSession, *, user: User, position_code: str, actor: User | None
) -> bool:
    """Take the post away from `user`. Returns False if they didn't hold it."""
    position = await get_position(session, position_code)
    removed = await session.scalar(
        delete(position_holders)
        .where(position_holders.c.position_id == position.id, position_holders.c.user_id == user.id)
        .returning(position_holders.c.position_id)
    )
    if removed is None:
        return False
    record_event(
        session,
        actor=actor,
        action="position.removed",
        entity_type=AUDIT_ENTITY,
        entity_id=user.id,
        details={"position": position.code},
    )
    await session.commit()
    await session.refresh(user, ["positions"])
    return True
