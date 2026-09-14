"""The one Jinja2 environment, shared by every router.

Server-rendered with no build step, per ADR-0006.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from budgetbetter.household.models import money

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))

# Household amounts are integer cents (ADR-0015), so templates format them
# through here rather than with the '%.2f' the REAL-valued domains use.
TEMPLATES.env.filters["money"] = money
