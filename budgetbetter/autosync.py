"""The automatic Refresh. See ADR-0007.

A launchd agent runs this daily at noon; it exits immediately unless today is a
Payday, because a launchd interval cannot express "every second Friday".
"""

import datetime as dt
import sys

from budgetbetter import db, plaid_client
from budgetbetter.config import get_settings
from budgetbetter.crypto import TokenCipher
from budgetbetter.schedule import is_payday, next_payday
from budgetbetter.sync import refresh_item


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv
    today = dt.date.today()

    if not force and not is_payday(today):
        print(f"{today}: not a payday, nothing to do (next is {next_payday(today)}).")
        return 0

    settings = get_settings()
    if settings.missing():
        print(f"Missing settings: {', '.join(settings.missing())}", file=sys.stderr)
        return 1

    connection = db.connect(settings.database_path)
    db.initialise(connection)
    client = plaid_client.build_client(settings)
    cipher = TokenCipher(settings.encryption_key)

    items = db.list_items(connection)
    if not items:
        print("No Items linked yet — open http://localhost:8000/connect first.")
        return 0

    failed = 0
    for item in items:
        name = item["institution_name"] or item["item_id"]
        try:
            result = refresh_item(
                connection,
                item["item_id"],
                plaid_client.make_page_fetcher(client, cipher.decrypt(item["access_token_encrypted"])),
                db.list_rules(connection),
            )
            print(
                f"{name}: {result.added} added, {result.modified} updated, "
                f"{result.removed} removed."
            )
        except Exception as exc:
            failed += 1
            print(f"{name}: refresh failed — {exc}", file=sys.stderr)

    connection.close()
    # A non-zero exit is what makes a failed Payday refresh visible in the log
    # rather than looking like a clean run.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
