"""Who is asking, and what they are allowed to see.

The banking side of this app is the Owner's alone — it is built on their actual
bank logins, and five roommates now have accounts in the same application. What
keeps those apart is `require_owner` on every budgeting and investing route,
not a second database. See ADR-0014.
"""

import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request

from budgetbetter.config import get_settings
from budgetbetter.deps import get_connection
from budgetbetter.household import db as household_db
from budgetbetter.household.models import Member

SESSION_COOKIE = "household_session"

# scrypt from the standard library rather than a C extension: this project
# holds itself to stdlib sqlite3 and no build step, and scrypt is memory-hard
# and perfectly sound for six accounts.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_secret(raw: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(raw.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${derived.hex()}"


def verify_secret(raw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    derived = hashlib.scrypt(raw.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(derived.hex(), digest_hex)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


# --- CSRF ------------------------------------------------------------------
#
# The app's forms are plain HTML posts (ADR-0006), which was safe while it was
# one person on localhost and is not once six people reach it over the
# internet. The token is derived from the session rather than stored, so it
# needs no table and dies with the session.


def _csrf_secret() -> bytes:
    return (get_settings().encryption_key or "budgetbetter-dev").encode()


def csrf_for_session(session_token: str) -> str:
    return hmac.new(_csrf_secret(), session_token.encode(), hashlib.sha256).hexdigest()


def csrf_token(request: Request) -> str:
    return csrf_for_session(request.cookies.get(SESSION_COOKIE, ""))


def verify_csrf(request: Request, submitted: str | None) -> None:
    if not hmac.compare_digest(csrf_token(request), submitted or ""):
        raise HTTPException(status_code=400, detail="Stale form. Reload the page and try again.")


# --- Who is asking ---------------------------------------------------------


def current_member(request: Request, connection=Depends(get_connection)) -> Member | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return household_db.member_for_session(connection, token)


def _bounce(connection) -> HTTPException:
    """Nobody signed in. Send them to register if the house is empty, since the
    first account to exist becomes the Owner."""
    target = "/household/register" if not household_db.count_members(connection) else "/household/login"
    return HTTPException(status_code=303, headers={"Location": target})


def require_member(
    member: Member | None = Depends(current_member),
    connection=Depends(get_connection),
) -> Member:
    if member is None:
        raise _bounce(connection)
    return member


def require_owner(
    member: Member | None = Depends(current_member),
    connection=Depends(get_connection),
) -> Member:
    """Guards everything Plaid-backed. A Member reaching one of those routes is
    a data breach, not a bug, so this is tested as such."""
    if member is None:
        raise _bounce(connection)
    if not member.is_owner:
        raise HTTPException(
            status_code=403,
            detail="The banking sections belong to the Owner. Household is at /household.",
        )
    return member
