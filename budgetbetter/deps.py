"""The request-scoped database connection, shared by every router.

Lives here rather than in `app.py` so the Household router can depend on the
same object the app composes with — and so a test overriding it overrides it
everywhere.
"""

from budgetbetter.config import get_settings
from budgetbetter.core import db


def get_connection():
    # The schema is created once at startup, not here: running DDL on every
    # request makes every page load contend for the single write lock. See
    # ADR-0018.
    connection = db.connect(get_settings().database_path)
    try:
        yield connection
    finally:
        connection.close()
