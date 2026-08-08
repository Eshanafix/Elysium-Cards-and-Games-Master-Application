"""
One-time "break glass" first-admin creation (docs/IMPLEMENTATION_PLAN.md
section 9.3). With an empty users collection, nobody can create the first
admin through the app (creating users requires an existing admin), so this
script inserts one directly. Refuses to run if any admin already exists --
after that, all account management happens through the app's Users screen.

Run by hand, in your own terminal, so the password never leaves this
machine or ends up in shell history:

    python -m elysium.bootstrap.create_admin
"""

import argparse
import getpass
import sys

from elysium.logging_setup import configure_logging
from elysium.models.users import ROLE_ADMIN, User
from elysium.repositories.master_repository import any_admin_exists
from elysium.services import auth_service
from elysium.services.mongo_client import check_connection


def create_first_admin(username: str, password: str) -> User:
    if any_admin_exists():
        raise RuntimeError("An admin account already exists. Use the app's Users screen to create more accounts.")

    # Reuses auth_service.create_user (not a separate insert path) so the
    # first admin gets the exact same USER_CREATED audit_events record as
    # every account created afterward through the app.
    return auth_service.create_user(username, password, [ROLE_ADMIN], created_by="BOOTSTRAP")


def main():
    configure_logging()

    parser = argparse.ArgumentParser(description="Create the first Elysium admin account (one-time bootstrap).")
    parser.add_argument("--username", help="Admin username (prompted if omitted)")
    parser.add_argument(
        "--password",
        help="Admin password. Prefer leaving this out and entering it at the secure prompt instead -- "
             "a --password value can be captured in shell history.",
    )
    args = parser.parse_args()

    status = check_connection()

    if not status.is_connected:
        print(f"Cannot create admin: MongoDB is unreachable ({status.detail})")
        sys.exit(1)

    username = args.username or input("Admin username: ").strip()

    if args.password:
        password = args.password
    else:
        password = getpass.getpass("Admin password: ")
        confirm = getpass.getpass("Confirm password: ")

        if password != confirm:
            print("Passwords did not match.")
            sys.exit(1)

    if not username or not password:
        print("Username and password are required.")
        sys.exit(1)

    try:
        create_first_admin(username, password)
    except (RuntimeError, auth_service.UsernameTakenError) as e:
        print(str(e))
        sys.exit(1)

    print(f"Admin account '{username}' created. You can now log in through the app.")


if __name__ == "__main__":
    main()
