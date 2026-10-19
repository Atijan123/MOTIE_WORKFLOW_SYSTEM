"""Manage users from the command line.

    docker compose exec api python -m app.core.identity.cli create-user \
        --email you@motie.gov.gm --name "Your Name" --role admin
    docker compose exec api python -m app.core.identity.cli assign-position \
        --email you@motie.gov.gm --position director_of_trade
    docker compose exec api python -m app.core.identity.cli remove-position \
        --email you@motie.gov.gm --position director_of_trade

The password is typed at a prompt, never passed as an argument, so it doesn't
end up in shell history or the process list. Repeat --role for several roles.
Position changes are written to the audit log with no actor (done from the CLI).
"""

import argparse
import asyncio
import getpass
import sys

from app.core.identity.service import (
    UnknownPosition,
    UnknownRole,
    UserAlreadyExists,
    WeakPassword,
    assign_position,
    create_user,
    get_user_by_email,
    remove_position,
)
from app.db.session import SessionLocal, engine


class UnknownUser(Exception):
    pass


async def _create_user(email: str, full_name: str, password: str, roles: list[str]) -> None:
    try:
        async with SessionLocal() as session:
            user = await create_user(
                session, email=email, full_name=full_name, password=password, role_codes=roles
            )
        print(f"Created user {user.id} <{user.email}> with roles: {', '.join(sorted(user.role_codes))}")
    finally:
        await engine.dispose()


async def _change_position(email: str, position: str, *, add: bool) -> None:
    try:
        async with SessionLocal() as session:
            user = await get_user_by_email(session, email)
            if user is None:
                raise UnknownUser(f"No user with email {email}.")
            change = assign_position if add else remove_position
            changed = await change(session, user=user, position_code=position, actor=None)
        if not changed:
            print(f"Nothing to do: {user.email} {'already holds' if add else 'does not hold'} {position}.")
        print(f"{user.email} now holds: {', '.join(sorted(user.position_codes)) or 'no positions'}")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.core.identity.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="create a user who can log in")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True, help="full name")
    create.add_argument("--role", action="append", required=True, help="role code; repeat for several")
    for name, help_text in [
        ("assign-position", "make a user a holder of a position"),
        ("remove-position", "take a position away from a user"),
    ]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--email", required=True)
        command.add_argument("--position", required=True, help="position code, e.g. director_of_trade")
    args = parser.parse_args(argv)

    try:
        if args.command == "create-user":
            password = getpass.getpass("Password: ")
            if getpass.getpass("Repeat password: ") != password:
                sys.exit("Passwords don't match.")
            asyncio.run(_create_user(args.email, args.name, password, args.role))
        else:
            asyncio.run(
                _change_position(args.email, args.position, add=args.command == "assign-position")
            )
    except (UserAlreadyExists, UnknownRole, WeakPassword, UnknownPosition, UnknownUser) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
