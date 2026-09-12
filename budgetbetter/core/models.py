"""Domain nouns shared by both budgeting and investing. See CONTEXT.md."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    """A single account inside an Item.

    `current_balance` is what the broker says the Account is worth, cash
    included. Only investing Refreshes report it. See ADR-0010.
    """

    account_id: str
    item_id: str
    name: str
    official_name: str | None
    mask: str | None
    type: str
    subtype: str | None
    current_balance: float | None = None

    @property
    def display_name(self) -> str:
        suffix = f" ••{self.mask}" if self.mask else ""
        return f"{self.name}{suffix}"
