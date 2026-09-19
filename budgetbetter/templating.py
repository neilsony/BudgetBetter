"""The one Jinja2 environment, shared by every router.

Server-rendered with no build step, per ADR-0006.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from budgetbetter.household.models import money

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


def dollars(amount: float | None) -> str:
    """A REAL-valued amount as currency, formatted identically to `money`.

    Household stores integer cents (ADR-0015) while budgeting and investing
    store floats, and the two used to render differently — `$1,025.00` on one
    side and `$1425.00` on the other. One design system cannot carry two money
    formats, so both now go through the same formatter.
    """
    if amount is None:
        return "—"
    return money(round(amount * 100))


TEMPLATES.env.filters["money"] = money
TEMPLATES.env.filters["dollars"] = dollars
