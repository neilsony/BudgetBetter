"""Household nouns. Vocabulary follows CONTEXT.md.

Every amount is an integer count of cents. See ADR-0015.
"""

import datetime as dt
from dataclasses import dataclass, field

# A Share in one of these states counts toward what someone owes. A Claim is
# still owed — asserting you sent the money does not clear the debt, only the
# payer confirming it does. See ADR-0016.
COUNTING_STATUSES = ("owed", "claimed")


def money(cents: int | None) -> str:
    """Cents as a currency string, e.g. -12345 -> '-$123.45'."""
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


@dataclass(frozen=True)
class Member:
    """One person in the Household, with a login of their own."""

    id: int
    name: str
    email: str
    role: str
    joined_on: dt.date
    left_on: dt.date | None = None

    @property
    def is_active(self) -> bool:
        """Departed Members join no new Expense but keep every old one."""
        return self.left_on is None

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.split() if p]
        return "".join(p[0].upper() for p in parts[:2]) or "?"


@dataclass(frozen=True)
class Share:
    """One Member's portion of one Expense."""

    id: int
    expense_id: int
    member_id: int
    amount_cents: int
    status: str
    claimed_at: str | None = None
    paid_at: str | None = None
    paid_by: int | None = None
    written_off: bool = False

    @property
    def counts(self) -> bool:
        """Whether this Share moves a Balance at all.

        A written-off Share is forgiven, a disputed one counts for nobody while
        the Dispute is open, and a voided one was removed by an upheld Dispute.
        """
        return self.status in COUNTING_STATUSES and not self.written_off

    @property
    def is_claimed(self) -> bool:
        return self.status == "claimed"

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"

    @property
    def is_disputed(self) -> bool:
        return self.status == "disputed"

    @property
    def amount(self) -> str:
        return money(self.amount_cents)


@dataclass(frozen=True)
class Expense:
    """Money one Member has already paid that others owe a portion of."""

    id: int
    payer_id: int
    created_by: int
    description: str
    total_cents: int
    kind: str
    split_mode: str
    incurred_on: dt.date
    created_at: str
    parent_expense_id: int | None = None
    voided_at: str | None = None
    voided_by: int | None = None
    shares: tuple[Share, ...] = field(default_factory=tuple)

    @property
    def is_void(self) -> bool:
        return self.voided_at is not None

    @property
    def is_rent(self) -> bool:
        return self.kind == "rent"

    @property
    def is_resolution(self) -> bool:
        return self.kind == "dispute_resolution"

    @property
    def disputable(self) -> bool:
        """Rent is settled outside the app, and a resolution must not start a
        chain of Disputes with no natural end. See ADR-0017 and ADR-0019.
        """
        return not self.is_void and not self.is_rent and not self.is_resolution

    @property
    def locked(self) -> bool:
        """True once *somebody else* has confirmed payment or raised a Dispute.

        A locked Expense can be neither edited nor deleted: the money has
        started moving, and the remedy for a mistake is a corrective Expense
        the other way. See ADR-0016 and ADR-0019.

        The payer's own Share is excluded. It is created already paid, so
        counting it would lock every Expense the instant it was raised and
        leave nothing ever deletable.
        """
        return any(
            share.status in ("paid", "disputed") and share.member_id != self.payer_id
            for share in self.shares
        )

    @property
    def settled(self) -> bool:
        """Nothing outstanding — drops off the dashboard into History."""
        return not any(s.counts for s in self.shares)

    @property
    def outstanding_cents(self) -> int:
        return sum(s.amount_cents for s in self.shares if s.counts)

    @property
    def amount(self) -> str:
        return money(self.total_cents)


@dataclass(frozen=True)
class Dispute:
    """A Member's objection to their own Share. Only the Owner resolves one."""

    id: int
    share_id: int
    raised_by: int
    reason: str
    status: str
    raised_at: str
    amended_amount_cents: int | None = None
    resolution_note: str | None = None
    resolved_by: int | None = None
    resolved_at: str | None = None

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"


@dataclass(frozen=True)
class Balance:
    """What one Member owes another, netted across both directions.

    Only ever between two people: this project never tells anyone to pay
    someone they did not transact with.
    """

    other: Member
    net_cents: int  # positive: you owe them. negative: they owe you.

    @property
    def you_owe(self) -> bool:
        return self.net_cents > 0

    @property
    def they_owe(self) -> bool:
        return self.net_cents < 0

    @property
    def amount(self) -> str:
        return money(abs(self.net_cents))


@dataclass(frozen=True)
class LedgerLine:
    """One Share seen from a particular Member's point of view, with the
    Expense and the counterparty it concerns — what a dashboard row shows."""

    share: Share
    expense: Expense
    counterparty: Member
    owed_by_me: bool
    dispute: Dispute | None = None

    @property
    def amount(self) -> str:
        return money(self.share.amount_cents)
