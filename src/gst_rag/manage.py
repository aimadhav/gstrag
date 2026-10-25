"""Local setup and explicit retention maintenance. Never prints credentials."""

import argparse
import getpass
import json

from .auth import PASSWORDS, Settings
from .models import Credentials
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-admin", help="Create first administrator using a hidden password prompt")
    init.add_argument("--username", default="admin")
    purge = commands.add_parser("purge-expired", help="Dry run by default; --apply deletes expired query data, never PDFs")
    purge.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings.local()
    store = Store(settings.db_path)
    if args.command == "init-admin":
        first, second = getpass.getpass("New administrator password (12+ characters): "), getpass.getpass("Confirm password: ")
        if first != second:
            raise SystemExit("Passwords did not match; no user created")
        body = Credentials(username=args.username, password=first)
        user = store.create_user(body.username, PASSWORDS.hash(body.password.get_secret_value()), "pro", "admin", bootstrap=True)
        print(json.dumps({"created_user_id": user["id"], "username": user["username"], "role": "admin"}))
    else:
        count = store.purge(apply=args.apply)
        print(json.dumps({"expired_queries": count, "deleted": bool(args.apply),
                          "note": "Deletes expired query content, private evidence, drafts, answers and their review events; source PDFs and accounts are retained."}))


if __name__ == "__main__":
    main()
