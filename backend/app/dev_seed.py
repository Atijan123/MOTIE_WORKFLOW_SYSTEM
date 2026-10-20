"""Fill a development database with one user per post in the ETLS chain, plus an applicant.

    docker compose run --rm tools python -m app.dev_seed

scripts/reset-dev.sh runs it after migrating. Development only: it refuses to
run unless APP_ENV=development, because it creates accounts with a known
password. Running it twice changes nothing.

Every account gets the password in DEV_SEED_PASSWORD, or "dev password 123".
"""

import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.identity.service import assign_position, create_user, get_user_by_email

DEFAULT_PASSWORD = "dev password 123"

# (email, name, roles, posts). ".test" is a domain reserved for testing, so
# these addresses can never belong to a real person.
USERS = [
    ("applicant@motie.test", "Dev Applicant", ["applicant"], []),
    ("records@motie.test", "Dev Records Officer", ["records_officer"], ["records_officer"]),
    ("minister@motie.test", "Dev Minister", ["minister"], ["minister"]),
    ("ps@motie.test", "Dev Permanent Secretary", ["permanent_secretary"], ["permanent_secretary"]),
    ("dps@motie.test", "Dev Deputy PS", ["director"], ["dps_admin_finance"]),
    ("director@motie.test", "Dev Director of Industry", ["director"], ["director_of_industry"]),
    ("officer@motie.test", "Dev Industry Officer", ["officer"], ["industry_officer"]),
    ("desk@motie.test", "Dev ETLS Desk Officer", ["officer"], ["etls_desk_officer"]),
    ("recorder@motie.test", "Dev Absence Recorder", ["officer", "absence_recorder"], []),
    ("admin@motie.test", "Dev Admin", ["admin"], []),
]


async def seed(session: AsyncSession, password: str) -> list[str]:
    """Create the users that don't exist yet and give them their posts. Returns the new emails."""
    created = []
    for email, name, roles, posts in USERS:
        user = await get_user_by_email(session, email)
        if user is None:
            user = await create_user(session, email=email, full_name=name, password=password, role_codes=roles)
            created.append(email)
        for post in posts:
            await assign_position(session, user=user, position_code=post, actor=None)
    return created


async def _main(password: str) -> None:
    # Imported here so the safety check in main() runs before any connection is made.
    from app.db.session import SessionLocal, engine

    try:
        async with SessionLocal() as session:
            created = await seed(session, password)
    finally:
        await engine.dispose()
    print(f"Created {len(created)} user(s); {len(USERS) - len(created)} already existed.")
    for email, _, roles, posts in USERS:
        print(f"  {email:<24} {', '.join(posts) or ', '.join(roles)}")
    print("Password for all of them: the DEV_SEED_PASSWORD you set, or the default in app/dev_seed.py.")


def main() -> None:
    if settings.app_env != "development":
        sys.exit(f"Refusing to seed: APP_ENV is '{settings.app_env}', not 'development'.")
    asyncio.run(_main(os.environ.get("DEV_SEED_PASSWORD") or DEFAULT_PASSWORD))


if __name__ == "__main__":
    main()
