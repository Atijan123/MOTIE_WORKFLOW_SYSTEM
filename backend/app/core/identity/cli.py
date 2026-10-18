"""Create users from the command line.

    docker compose exec api python -m app.core.identity.cli create-user \
        --email you@motie.gov.gm --name "Your Name" --role admin

The password is typed at a prompt, never passed as an argument, so it doesn't
end up in shell history or the process list. Repeat --role for several roles.
"""

import argparse
import asyncio
import getpass
import sys

from app.core.identity.service import UnknownRole, UserAlreadyExists, WeakPassword, create_user
from app.db.session import SessionLocal, engine


async def _create_user(email: str, full_name: str, password: str, roles: list[str]) -> None:
    try:
        async with SessionLocal() as session:
            user = await create_user(
                session, email=email, full_name=full_name, password=password, role_codes=roles
            )
        print(f"Created user {user.id} <{user.email}> with roles: {', '.join(sorted(user.role_codes))}")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.core.identity.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="create a user who can log in")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True, help="full name")
    create.add_argument("--role", action="append", required=True, help="role code; repeat for several")
    args = parser.parse_args(argv)

    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords don't match.")

    try:
        asyncio.run(_create_user(args.email, args.name, password, args.role))
    except (UserAlreadyExists, UnknownRole, WeakPassword) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
