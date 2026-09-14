"""Resolving a Dispute, and spreading what it removes.

When an amount comes off a Share somebody has to carry it, because the payer is
genuinely out of pocket for the full total. It goes to everyone else who had a
live Share on that Expense — the payer included, whose portion is self-owed and
so is simply absorbed. See ADR-0017.
"""

import sqlite3
from dataclasses import dataclass

from budgetbetter.household import db as household_db
from budgetbetter.household import ledger
from budgetbetter.household.models import Expense


@dataclass(frozen=True)
class Resolution:
    """What resolving a Dispute did, for the audit trail and notifications."""

    outcome: str
    expense: Expense
    resolution_expense_id: int | None = None
    redistributed_cents: int = 0
    touched_member_ids: tuple[int, ...] = ()


class DisputeError(ValueError):
    """A Dispute that cannot be resolved the way it was asked to be."""


def participants_for_redistribution(expense: Expense, disputer_id: int) -> list[int]:
    """Everyone left on the Expense to carry the amount.

    Already-paid Shares count: their holder was part of this Expense and simply
    acquires a new, separate debt. Only the disputer and Shares already voided
    by an earlier Dispute drop out.
    """
    return [
        share.member_id
        for share in expense.shares
        if share.status != "void" and share.member_id != disputer_id
    ]


def resolve(
    connection: sqlite3.Connection,
    dispute_id: int,
    *,
    outcome: str,
    resolver_id: int,
    note: str | None = None,
    amended_cents: int | None = None,
) -> Resolution:
    """Uphold, deny, or amend a pending Dispute.

    Caller holds the write transaction — this reads and writes across four
    tables and must not be half-applied.
    """
    dispute = household_db.get_dispute(connection, dispute_id)
    if dispute is None:
        raise DisputeError("No such dispute.")
    if not dispute.is_pending:
        raise DisputeError("That dispute has already been resolved.")

    share = household_db.get_share(connection, dispute.share_id)
    if share is None:
        raise DisputeError("The disputed Share has gone.")
    expense = household_db.get_expense(connection, share.expense_id)
    if expense is None:
        raise DisputeError("The disputed Expense has gone.")

    if outcome == "denied":
        return _deny(connection, dispute_id, share, expense, resolver_id, note)
    if outcome == "upheld":
        return _uphold(connection, dispute_id, share, expense, resolver_id, note)
    if outcome == "amended":
        return _amend(connection, dispute_id, share, expense, resolver_id, note, amended_cents)
    raise DisputeError(f"Unknown outcome {outcome!r}.")


def _deny(connection, dispute_id, share, expense, resolver_id, note) -> Resolution:
    """The Share returns exactly as it was. Nothing is redistributed."""
    household_db.set_share_status(connection, share.id, "owed")
    household_db.resolve_dispute(
        connection, dispute_id, status="denied", resolved_by=resolver_id, note=note
    )
    household_db.record_event(
        connection,
        actor_id=resolver_id,
        entity="dispute",
        entity_id=dispute_id,
        action="denied",
        before={"share_status": "disputed", "amount_cents": share.amount_cents},
        after={"share_status": "owed", "amount_cents": share.amount_cents},
    )
    return Resolution(outcome="denied", expense=expense)


def _uphold(connection, dispute_id, share, expense, resolver_id, note) -> Resolution:
    """The Share is voided and its whole amount redistributed."""
    household_db.set_share_status(connection, share.id, "void")
    household_db.resolve_dispute(
        connection, dispute_id, status="upheld", resolved_by=resolver_id, note=note
    )
    resolution_id, touched = _raise_resolution_expense(
        connection, expense, share.member_id, share.amount_cents, resolver_id
    )
    household_db.record_event(
        connection,
        actor_id=resolver_id,
        entity="dispute",
        entity_id=dispute_id,
        action="upheld",
        before={"share_status": "disputed", "amount_cents": share.amount_cents},
        after={"share_status": "void", "redistributed_cents": share.amount_cents},
    )
    return Resolution(
        outcome="upheld",
        expense=expense,
        resolution_expense_id=resolution_id,
        redistributed_cents=share.amount_cents,
        touched_member_ids=tuple(touched),
    )


def _amend(connection, dispute_id, share, expense, resolver_id, note, amended_cents) -> Resolution:
    """The Share is corrected, and only the difference moves.

    This is the common outcome: most real objections are "my share should be
    forty dollars, not a hundred" rather than "I owe nothing at all".
    """
    if amended_cents is None or amended_cents < 0:
        raise DisputeError("An amended Share needs an amount of zero or more.")
    if amended_cents > share.amount_cents:
        raise DisputeError("An amendment can only lower a Share, never raise it.")

    difference = share.amount_cents - amended_cents
    household_db.set_share_amount(connection, share.id, amended_cents)
    household_db.set_share_status(connection, share.id, "owed" if amended_cents else "void")
    household_db.resolve_dispute(
        connection,
        dispute_id,
        status="amended",
        resolved_by=resolver_id,
        note=note,
        amended_amount_cents=amended_cents,
    )

    resolution_id, touched = (None, [])
    if difference:
        resolution_id, touched = _raise_resolution_expense(
            connection, expense, share.member_id, difference, resolver_id
        )

    household_db.record_event(
        connection,
        actor_id=resolver_id,
        entity="dispute",
        entity_id=dispute_id,
        action="amended",
        before={"amount_cents": share.amount_cents},
        after={"amount_cents": amended_cents, "redistributed_cents": difference},
    )
    return Resolution(
        outcome="amended",
        expense=expense,
        resolution_expense_id=resolution_id,
        redistributed_cents=difference,
        touched_member_ids=tuple(touched),
    )


def _raise_resolution_expense(
    connection, expense: Expense, disputer_id: int, amount_cents: int, actor_id: int
) -> tuple[int | None, list[int]]:
    """Create the `Dispute resolution — …` Expense that carries the amount.

    It is an ordinary Expense owed to the same payer, so marking paid, the
    audit trail and the dashboard all work on it unchanged. It can never itself
    be disputed — that chain would have no natural end.
    """
    participants = participants_for_redistribution(expense, disputer_id)
    if not participants:
        # Nobody left to carry it: the payer simply absorbs the whole amount,
        # which is what already happened when the Share was voided.
        return None, []

    amounts = ledger.redistribute(amount_cents, participants, expense.payer_id)
    resolution_id = household_db.create_expense(
        connection,
        payer_id=expense.payer_id,
        created_by=actor_id,
        description=f"Dispute resolution — {expense.description}",
        total_cents=amount_cents,
        kind="dispute_resolution",
        split_mode="resolution",
        incurred_on=expense.incurred_on,
        share_amounts=amounts,
        parent_expense_id=expense.id,
    )
    household_db.record_event(
        connection,
        actor_id=actor_id,
        entity="expense",
        entity_id=resolution_id,
        action="created_from_dispute",
        after={"parent_expense_id": expense.id, "total_cents": amount_cents},
    )
    return resolution_id, list(amounts)
