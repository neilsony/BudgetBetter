"""Telling people their Balance moved without them doing anything.

Rows only. Nothing is sent anywhere yet — an email sender drains this same
table once the app is deployed, so adding it changes nothing about the ledger.
Every notification goes to the Members the change actually touches, plus the
Owner, and never back to whoever made the change.
"""

import sqlite3

from budgetbetter.household import db as household_db
from budgetbetter.household.models import money


def _owner_id(connection: sqlite3.Connection) -> int | None:
    row = connection.execute(
        "SELECT id FROM members WHERE role = 'owner' ORDER BY id LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def fan_out(
    connection: sqlite3.Connection,
    *,
    member_ids,
    kind: str,
    body: str,
    actor_id: int | None = None,
    link: str | None = None,
    event_id: int | None = None,
) -> None:
    targets = set(member_ids)
    owner_id = _owner_id(connection)
    if owner_id is not None:
        targets.add(owner_id)
    targets.discard(actor_id)
    for member_id in sorted(targets):
        household_db.add_notification(
            connection,
            member_id=member_id,
            kind=kind,
            body=body,
            link=link,
            event_id=event_id,
        )


def expense_created(connection, expense, actor_id, event_id=None) -> None:
    who = household_db.get_member(connection, expense.payer_id)
    fan_out(
        connection,
        member_ids=[s.member_id for s in expense.shares],
        kind="expense_created",
        body=f"{who.name if who else 'Someone'} added “{expense.description}” "
        f"for {money(expense.total_cents)}.",
        actor_id=actor_id,
        link=f"/household/expenses/{expense.id}",
        event_id=event_id,
    )


def share_claimed(connection, expense, share, actor_id, event_id=None) -> None:
    who = household_db.get_member(connection, share.member_id)
    fan_out(
        connection,
        member_ids=[expense.payer_id],
        kind="share_claimed",
        body=f"{who.name if who else 'Someone'} says they have sent "
        f"{money(share.amount_cents)} for “{expense.description}”. Confirm it to clear the debt.",
        actor_id=actor_id,
        link=f"/household/expenses/{expense.id}",
        event_id=event_id,
    )


def share_settled(connection, expense, share, actor_id, event_id=None) -> None:
    fan_out(
        connection,
        member_ids=[share.member_id],
        kind="share_settled",
        body=f"Your {money(share.amount_cents)} for “{expense.description}” is marked paid.",
        actor_id=actor_id,
        link=f"/household/expenses/{expense.id}",
        event_id=event_id,
    )


def dispute_raised(connection, expense, share, reason, actor_id, event_id=None) -> None:
    who = household_db.get_member(connection, share.member_id)
    fan_out(
        connection,
        member_ids=[expense.payer_id],
        kind="dispute_raised",
        body=f"{who.name if who else 'Someone'} disputed {money(share.amount_cents)} "
        f"on “{expense.description}”: {reason}",
        actor_id=actor_id,
        link=f"/household/disputes",
        event_id=event_id,
    )


def dispute_resolved(connection, expense, share, outcome, touched, actor_id, event_id=None) -> None:
    fan_out(
        connection,
        member_ids=[share.member_id, expense.payer_id, *touched],
        kind="dispute_resolved",
        body=f"A dispute on “{expense.description}” was {outcome}.",
        actor_id=actor_id,
        link=f"/household/expenses/{expense.id}",
        event_id=event_id,
    )


def expense_changed(connection, expense, what, actor_id, event_id=None) -> None:
    fan_out(
        connection,
        member_ids=[s.member_id for s in expense.shares],
        kind="expense_changed",
        body=f"“{expense.description}” was {what}.",
        actor_id=actor_id,
        link=f"/household/expenses/{expense.id}",
        event_id=event_id,
    )


def debt_written_off(connection, expense, share, actor_id, event_id=None) -> None:
    fan_out(
        connection,
        member_ids=[expense.payer_id, share.member_id],
        kind="write_off",
        body=f"{money(share.amount_cents)} owed on “{expense.description}” was written off.",
        actor_id=actor_id,
        link=f"/household/expenses/{expense.id}",
        event_id=event_id,
    )
