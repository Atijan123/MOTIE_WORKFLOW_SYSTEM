"""Business logic for users. Endpoints and the CLI call these; they never write SQL themselves."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.models import Role, User
from app.core.identity.security import hash_password

# NIST SP 800-63B recommends length over complexity rules. 12 is a common floor
# for staff accounts.
MIN_PASSWORD_LENGTH = 12


class UserAlreadyExists(Exception):
    pass


class UnknownRole(Exception):
    pass


class WeakPassword(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == normalize_email(email)))


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    password: str,
    role_codes: list[str],
) -> User:
    email = normalize_email(email)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if await get_user_by_email(session, email):
        raise UserAlreadyExists(f"A user with email {email} already exists.")

    roles = (await session.scalars(select(Role).where(Role.code.in_(role_codes)))).all()
    missing = set(role_codes) - {role.code for role in roles}
    if missing:
        raise UnknownRole(f"Unknown role(s): {', '.join(sorted(missing))}")

    user = User(
        email=email,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        roles=list(roles),
    )
    session.add(user)
    await session.commit()
    return user
