"""Splitting money and deriving Balances. Pure functions, no database.

Everything here is integer cents. Splitting is integer division plus an
explicit remainder, so Shares always add back to exactly the total and the
allocation is reproducible. See ADR-0015.
"""

from collections import defaultdict

from budgetbetter.household.models import Balance, Expense, Member, Share

SPLIT_MODES = ("equal_all", "equal_selected", "custom", "reimbursement")


class SplitError(ValueError):
    """A split that would not add back to the Expense total."""


def penny_order(member_ids: list[int], payer_id: int | None) -> list[int]:
    """Who gets the leftover pennies, in order: the payer first, then by id.

    Stable and deterministic, so the same split always allocates the same way.
    """
    ordered = sorted(member_ids)
    if payer_id in ordered:
        ordered.remove(payer_id)
        ordered.insert(0, payer_id)
    return ordered


def allocate_equally(
    total_cents: int, member_ids: list[int], payer_id: int | None = None
) -> dict[int, int]:
    """Split a total as evenly as cents allow, losing nothing.

    $100 three ways is 3334 / 3333 / 3333, not three values that add to
    $99.99. The odd pennies go to the payer first — they are the one out of
    pocket — then in stable Member order.
    """
    if not member_ids:
        raise SplitError("A split needs at least one Member.")
    if total_cents < 0:
        raise SplitError("An Expense total cannot be negative.")

    unique = list(dict.fromkeys(member_ids))
    base, remainder = divmod(total_cents, len(unique))
    amounts = {member_id: base for member_id in unique}
    for member_id in penny_order(unique, payer_id)[:remainder]:
        amounts[member_id] += 1
    return amounts


def shares_for(
    mode: str,
    *,
    total_cents: int,
    member_ids: list[int],
    payer_id: int,
    custom_cents: dict[int, int] | None = None,
) -> dict[int, int]:
    """The Shares an Expense should carry, by split mode.

    `equal_all` and `equal_selected` always include the payer: the total is
    what they are seeking reimbursement for, and their own portion of it is
    theirs. `reimbursement` is the opposite — they bought something entirely
    for someone else and want all of it back, so they take no Share at all.
    `custom` is whatever was typed, and a Member given nothing gets no Share.
    """
    if mode in ("equal_all", "equal_selected"):
        ids = list(dict.fromkeys([payer_id, *member_ids]))
        return allocate_equally(total_cents, ids, payer_id)

    if mode == "reimbursement":
        ids = [m for m in dict.fromkeys(member_ids) if m != payer_id]
        if not ids:
            raise SplitError("A reimbursement needs someone other than the payer.")
        return allocate_equally(total_cents, ids, payer_id)

    if mode == "custom":
        amounts = {m: c for m, c in (custom_cents or {}).items() if c}
        if not amounts:
            raise SplitError("A custom split needs at least one amount.")
        if any(c < 0 for c in amounts.values()):
            raise SplitError("A Share cannot be negative.")
        check_sums_to_total(amounts, total_cents)
        return amounts

    raise SplitError(f"Unknown split mode {mode!r}.")


def check_sums_to_total(amounts: dict[int, int], total_cents: int) -> None:
    """Shares must add to the Expense total exactly — never nearly."""
    total = sum(amounts.values())
    if total != total_cents:
        raise SplitError(
            f"Shares add up to {total / 100:.2f}, but the total is {total_cents / 100:.2f}."
        )


def redistribute(
    amount_cents: int, participant_ids: list[int], payer_id: int
) -> dict[int, int]:
    """Spread an upheld Dispute's amount over everyone else on the Expense.

    The payer is included: they authored the split, and excluding them would
    mean the person who set a wrong amount bears none of the cost of it while
    four uninvolved people bear all of it. Their portion is self-owed and so
    is simply absorbed. See ADR-0017.
    """
    if not participant_ids:
        raise SplitError("Nobody is left to carry the disputed amount.")
    return allocate_equally(amount_cents, participant_ids, payer_id)


# --- Balances --------------------------------------------------------------


def net_by_member(
    lines: list[tuple[Share, Expense]], me_id: int
) -> dict[int, int]:
    """What this Member owes each other Member, netted both ways.

    Positive means I owe them. A Share only counts when it is live: voided
    Expenses, settled Shares, open Disputes and written-off debts all drop
    out. Nothing is ever netted across three people — you are only told to pay
    someone you actually transacted with.
    """
    net: dict[int, int] = defaultdict(int)
    for share, expense in lines:
        if expense.is_void or not share.counts:
            continue
        if share.member_id == me_id and expense.payer_id != me_id:
            net[expense.payer_id] += share.amount_cents
        elif expense.payer_id == me_id and share.member_id != me_id:
            net[share.member_id] -= share.amount_cents
    return {member_id: cents for member_id, cents in net.items() if cents}


def balances(
    lines: list[tuple[Share, Expense]], me_id: int, members: dict[int, Member]
) -> list[Balance]:
    """Per-counterparty Balances, biggest debt first."""
    net = net_by_member(lines, me_id)
    found = [
        Balance(other=members[member_id], net_cents=cents)
        for member_id, cents in net.items()
        if member_id in members
    ]
    return sorted(found, key=lambda b: -b.net_cents)


def totals(balances_: list[Balance]) -> tuple[int, int]:
    """(what I owe in total, what I am owed in total), both positive.

    Kept as two figures rather than one signed number because they answer
    different questions, and a single net figure hides a Member who is owed a
    lot by one person and owes a lot to another.
    """
    owed = sum(b.net_cents for b in balances_ if b.net_cents > 0)
    owed_to_me = sum(-b.net_cents for b in balances_ if b.net_cents < 0)
    return owed, owed_to_me
