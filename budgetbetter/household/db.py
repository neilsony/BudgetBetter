"""The Household store: hand-written SQL, rows mapped to dataclasses by hand.

Nothing in here opens or commits a transaction. Callers wrap whole operations
in `core.db.writing`, which takes the write lock up front — a Household change
is almost always a read-modify-write, and those are exactly what SQLite will
not let a deferred transaction retry. See ADR-0018.
"""

import datetime as dt
import json
import sqlite3

from budgetbetter.household.models import Dispute, Expense, Member, Share


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _to_member(row: sqlite3.Row) -> Member:
    return Member(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        role=row["role"],
        joined_on=dt.date.fromisoformat(row["joined_on"]),
        left_on=dt.date.fromisoformat(row["left_on"]) if row["left_on"] else None,
    )


def _to_share(row: sqlite3.Row) -> Share:
    keys = row.keys()
    return Share(
        id=row["id"],
        expense_id=row["expense_id"],
        member_id=row["member_id"],
        amount_cents=row["amount_cents"],
        status=row["status"],
        claimed_at=row["claimed_at"],
        paid_at=row["paid_at"],
        paid_by=row["paid_by"],
        written_off=bool(row["written_off"]) if "written_off" in keys else False,
    )


def _to_expense(row: sqlite3.Row, shares: tuple[Share, ...] = ()) -> Expense:
    return Expense(
        id=row["id"],
        payer_id=row["payer_id"],
        created_by=row["created_by"],
        description=row["description"],
        total_cents=row["total_cents"],
        kind=row["kind"],
        split_mode=row["split_mode"],
        incurred_on=dt.date.fromisoformat(row["incurred_on"]),
        created_at=row["created_at"],
        parent_expense_id=row["parent_expense_id"],
        voided_at=row["voided_at"],
        voided_by=row["voided_by"],
        shares=shares,
    )


def _to_dispute(row: sqlite3.Row) -> Dispute:
    return Dispute(
        id=row["id"],
        share_id=row["share_id"],
        raised_by=row["raised_by"],
        reason=row["reason"],
        status=row["status"],
        raised_at=row["raised_at"],
        amended_amount_cents=row["amended_amount_cents"],
        resolution_note=row["resolution_note"],
        resolved_by=row["resolved_by"],
        resolved_at=row["resolved_at"],
    )


# --- Audit -----------------------------------------------------------------


def record_event(
    connection: sqlite3.Connection,
    *,
    actor_id: int | None,
    entity: str,
    entity_id: int,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
) -> int:
    """Append one immutable row to the audit trail.

    Both sides of the change are stored rather than just an action name, so the
    history stays rich enough to reconstruct from later.
    """
    cursor = connection.execute(
        """
        INSERT INTO events (at, actor_id, entity, entity_id, action, before_json, after_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _now(),
            actor_id,
            entity,
            entity_id,
            action,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
        ),
    )
    return int(cursor.lastrowid)


def list_events(connection: sqlite3.Connection, *, limit: int = 200) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def events_for(connection: sqlite3.Connection, entity: str, entity_id: int) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM events WHERE entity = ? AND entity_id = ? ORDER BY id",
        (entity, entity_id),
    ).fetchall()


# --- Members ---------------------------------------------------------------


def count_members(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM members").fetchone()[0]


def create_member(
    connection: sqlite3.Connection,
    *,
    name: str,
    email: str,
    password_hash: str,
    role: str = "member",
) -> int:
    today = dt.date.today().isoformat()
    cursor = connection.execute(
        """
        INSERT INTO members (name, email, password_hash, role, joined_on, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (name, email.strip().lower(), password_hash, role, today, _now()),
    )
    return int(cursor.lastrowid)


def get_member(connection: sqlite3.Connection, member_id: int) -> Member | None:
    row = connection.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    return _to_member(row) if row else None


def get_member_by_email(connection: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM members WHERE email = ?", (email.strip().lower(),)
    ).fetchone()


def list_members(connection: sqlite3.Connection, *, active_only: bool = False) -> list[Member]:
    sql = "SELECT * FROM members"
    if active_only:
        sql += " WHERE left_on IS NULL"
    sql += " ORDER BY name"
    return [_to_member(row) for row in connection.execute(sql).fetchall()]


def members_by_id(connection: sqlite3.Connection) -> dict[int, Member]:
    return {m.id: m for m in list_members(connection)}


def set_left_on(connection: sqlite3.Connection, member_id: int, on: dt.date | None) -> None:
    """Unregister a Member, or bring them back. Never deletes them."""
    connection.execute(
        "UPDATE members SET left_on = ? WHERE id = ?",
        (on.isoformat() if on else None, member_id),
    )


# --- House PIN -------------------------------------------------------------


def get_pin_hash(connection: sqlite3.Connection) -> str | None:
    row = connection.execute("SELECT pin_hash FROM house_settings WHERE id = 1").fetchone()
    return row["pin_hash"] if row else None


def set_pin_hash(connection: sqlite3.Connection, pin_hash: str) -> None:
    connection.execute(
        """
        INSERT INTO house_settings (id, pin_hash, updated_at)
        VALUES (1, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            pin_hash   = excluded.pin_hash,
            updated_at = excluded.updated_at
        """,
        (pin_hash, _now()),
    )


# --- Sessions --------------------------------------------------------------


def create_session(
    connection: sqlite3.Connection, *, token: str, member_id: int, days: int = 30
) -> None:
    expires = dt.datetime.now() + dt.timedelta(days=days)
    connection.execute(
        "INSERT INTO sessions (token, member_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, member_id, _now(), expires.isoformat(timespec="seconds")),
    )


def member_for_session(connection: sqlite3.Connection, token: str) -> Member | None:
    row = connection.execute(
        """
        SELECT m.* FROM sessions s
        JOIN members m ON m.id = s.member_id
        WHERE s.token = ? AND s.expires_at > ?
        """,
        (token, _now()),
    ).fetchone()
    return _to_member(row) if row else None


def delete_session(connection: sqlite3.Connection, token: str) -> None:
    connection.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --- Expenses and Shares ---------------------------------------------------


def create_expense(
    connection: sqlite3.Connection,
    *,
    payer_id: int,
    created_by: int,
    description: str,
    total_cents: int,
    kind: str,
    split_mode: str,
    incurred_on: dt.date,
    share_amounts: dict[int, int],
    parent_expense_id: int | None = None,
) -> int:
    """Write an Expense and its Shares.

    The payer's own Share is created already paid: they obviously settled their
    own portion by paying the whole thing. It stays reversible like any other.
    """
    cursor = connection.execute(
        """
        INSERT INTO expenses (payer_id, created_by, description, total_cents, kind,
                              split_mode, parent_expense_id, incurred_on, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payer_id,
            created_by,
            description,
            total_cents,
            kind,
            split_mode,
            parent_expense_id,
            incurred_on.isoformat(),
            _now(),
        ),
    )
    expense_id = int(cursor.lastrowid)

    for member_id, amount_cents in share_amounts.items():
        is_payer = member_id == payer_id
        connection.execute(
            """
            INSERT INTO shares (expense_id, member_id, amount_cents, status, paid_at, paid_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                expense_id,
                member_id,
                amount_cents,
                "paid" if is_payer else "owed",
                _now() if is_payer else None,
                payer_id if is_payer else None,
            ),
        )
    return expense_id


def get_expense(connection: sqlite3.Connection, expense_id: int) -> Expense | None:
    row = connection.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if not row:
        return None
    return _to_expense(row, shares=tuple(list_shares(connection, expense_id)))


def list_shares(connection: sqlite3.Connection, expense_id: int) -> list[Share]:
    rows = connection.execute(
        """
        SELECT s.*, (w.id IS NOT NULL) AS written_off
        FROM shares s
        LEFT JOIN write_offs w ON w.share_id = s.id
        WHERE s.expense_id = ?
        ORDER BY s.id
        """,
        (expense_id,),
    ).fetchall()
    return [_to_share(row) for row in rows]


def list_expenses(connection: sqlite3.Connection, *, limit: int = 300) -> list[Expense]:
    """Every Expense in the Household, newest first.

    Deliberately not filtered to the caller: a Member sees the whole house's
    ledger, including Expenses they are not on. Only their own dashboard
    totals are theirs alone.
    """
    rows = connection.execute(
        "SELECT * FROM expenses ORDER BY incurred_on DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    by_expense: dict[int, list[Share]] = {}
    for share_row in connection.execute(
        """
        SELECT s.*, (w.id IS NOT NULL) AS written_off
        FROM shares s
        LEFT JOIN write_offs w ON w.share_id = s.id
        ORDER BY s.id
        """
    ).fetchall():
        by_expense.setdefault(share_row["expense_id"], []).append(_to_share(share_row))
    return [_to_expense(row, tuple(by_expense.get(row["id"], []))) for row in rows]


def all_lines(connection: sqlite3.Connection) -> list[tuple[Share, Expense]]:
    """Every (Share, Expense) pair — what the Balance maths walks."""
    return [(share, expense) for expense in list_expenses(connection) for share in expense.shares]


def get_share(connection: sqlite3.Connection, share_id: int) -> Share | None:
    row = connection.execute(
        """
        SELECT s.*, (w.id IS NOT NULL) AS written_off
        FROM shares s
        LEFT JOIN write_offs w ON w.share_id = s.id
        WHERE s.id = ?
        """,
        (share_id,),
    ).fetchone()
    return _to_share(row) if row else None


def set_share_status(
    connection: sqlite3.Connection,
    share_id: int,
    status: str,
    *,
    paid_by: int | None = None,
) -> None:
    connection.execute(
        """
        UPDATE shares SET
            status     = ?,
            claimed_at = CASE WHEN ? = 'claimed' THEN ? ELSE NULL END,
            paid_at    = CASE WHEN ? = 'paid' THEN ? ELSE NULL END,
            paid_by    = CASE WHEN ? = 'paid' THEN ? ELSE NULL END
        WHERE id = ?
        """,
        (status, status, _now(), status, _now(), status, paid_by, share_id),
    )


def set_share_amount(connection: sqlite3.Connection, share_id: int, amount_cents: int) -> None:
    connection.execute(
        "UPDATE shares SET amount_cents = ? WHERE id = ?", (amount_cents, share_id)
    )


def update_expense(
    connection: sqlite3.Connection,
    expense_id: int,
    *,
    description: str,
    total_cents: int,
    incurred_on: dt.date,
    share_amounts: dict[int, int],
) -> None:
    """Rewrite an unlocked Expense and replace its Shares wholesale."""
    connection.execute(
        "UPDATE expenses SET description = ?, total_cents = ?, incurred_on = ? WHERE id = ?",
        (description, total_cents, incurred_on.isoformat(), expense_id),
    )
    row = connection.execute(
        "SELECT payer_id FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()
    payer_id = row["payer_id"]
    connection.execute("DELETE FROM shares WHERE expense_id = ?", (expense_id,))
    for member_id, amount_cents in share_amounts.items():
        is_payer = member_id == payer_id
        connection.execute(
            """
            INSERT INTO shares (expense_id, member_id, amount_cents, status, paid_at, paid_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                expense_id,
                member_id,
                amount_cents,
                "paid" if is_payer else "owed",
                _now() if is_payer else None,
                payer_id if is_payer else None,
            ),
        )


def void_expense(connection: sqlite3.Connection, expense_id: int, by_member_id: int) -> None:
    """Mark an Expense void. The row stays; nothing here is hard-deleted."""
    connection.execute(
        "UPDATE expenses SET voided_at = ?, voided_by = ? WHERE id = ?",
        (_now(), by_member_id, expense_id),
    )


def rent_expense_for_month(
    connection: sqlite3.Connection, year: int, month: int
) -> sqlite3.Row | None:
    """Whether Rent has already been raised this month, so a second press of
    the button warns instead of silently doubling everyone's debt."""
    prefix = f"{year:04d}-{month:02d}-"
    return connection.execute(
        """
        SELECT * FROM expenses
        WHERE kind = 'rent' AND voided_at IS NULL AND incurred_on LIKE ?
        ORDER BY id DESC LIMIT 1
        """,
        (prefix + "%",),
    ).fetchone()


# --- Disputes --------------------------------------------------------------


def raise_dispute(
    connection: sqlite3.Connection, *, share_id: int, raised_by: int, reason: str
) -> int:
    cursor = connection.execute(
        "INSERT INTO disputes (share_id, raised_by, reason, status, raised_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (share_id, raised_by, reason, _now()),
    )
    return int(cursor.lastrowid)


def get_dispute(connection: sqlite3.Connection, dispute_id: int) -> Dispute | None:
    row = connection.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
    return _to_dispute(row) if row else None


def pending_dispute_for_share(connection: sqlite3.Connection, share_id: int) -> Dispute | None:
    row = connection.execute(
        "SELECT * FROM disputes WHERE share_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
        (share_id,),
    ).fetchone()
    return _to_dispute(row) if row else None


def disputes_by_share(connection: sqlite3.Connection) -> dict[int, Dispute]:
    rows = connection.execute(
        "SELECT * FROM disputes WHERE status = 'pending' ORDER BY id"
    ).fetchall()
    return {row["share_id"]: _to_dispute(row) for row in rows}


def list_disputes(connection: sqlite3.Connection, *, pending_only: bool = False) -> list[Dispute]:
    sql = "SELECT * FROM disputes"
    if pending_only:
        sql += " WHERE status = 'pending'"
    sql += " ORDER BY id DESC"
    return [_to_dispute(row) for row in connection.execute(sql).fetchall()]


def resolve_dispute(
    connection: sqlite3.Connection,
    dispute_id: int,
    *,
    status: str,
    resolved_by: int,
    note: str | None = None,
    amended_amount_cents: int | None = None,
) -> None:
    connection.execute(
        """
        UPDATE disputes SET
            status               = ?,
            resolved_by          = ?,
            resolved_at          = ?,
            resolution_note      = ?,
            amended_amount_cents = ?
        WHERE id = ?
        """,
        (status, resolved_by, _now(), note, amended_amount_cents, dispute_id),
    )


# --- Write-offs ------------------------------------------------------------


def write_off_share(
    connection: sqlite3.Connection, *, share_id: int, by_member_id: int, reason: str | None
) -> int:
    cursor = connection.execute(
        "INSERT INTO write_offs (share_id, written_off_by, reason, at) VALUES (?, ?, ?, ?)",
        (share_id, by_member_id, reason, _now()),
    )
    return int(cursor.lastrowid)


# --- Rent ------------------------------------------------------------------


def rent_shares(connection: sqlite3.Connection) -> dict[int, int]:
    rows = connection.execute("SELECT member_id, amount_cents FROM rent_shares").fetchall()
    return {row["member_id"]: row["amount_cents"] for row in rows}


def set_rent_share(connection: sqlite3.Connection, member_id: int, amount_cents: int) -> None:
    connection.execute(
        """
        INSERT INTO rent_shares (member_id, amount_cents, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT (member_id) DO UPDATE SET
            amount_cents = excluded.amount_cents,
            updated_at   = excluded.updated_at
        """,
        (member_id, amount_cents, _now()),
    )


def clear_rent_share(connection: sqlite3.Connection, member_id: int) -> None:
    connection.execute("DELETE FROM rent_shares WHERE member_id = ?", (member_id,))


# --- Notifications ---------------------------------------------------------


def add_notification(
    connection: sqlite3.Connection,
    *,
    member_id: int,
    kind: str,
    body: str,
    link: str | None = None,
    event_id: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO notifications (member_id, event_id, kind, body, link, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (member_id, event_id, kind, body, link, _now()),
    )


def list_notifications(
    connection: sqlite3.Connection, member_id: int, *, limit: int = 50
) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM notifications WHERE member_id = ? ORDER BY id DESC LIMIT ?",
        (member_id, limit),
    ).fetchall()


def unseen_count(connection: sqlite3.Connection, member_id: int) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM notifications WHERE member_id = ? AND seen_at IS NULL",
        (member_id,),
    ).fetchone()[0]


def mark_notifications_seen(connection: sqlite3.Connection, member_id: int) -> None:
    connection.execute(
        "UPDATE notifications SET seen_at = ? WHERE member_id = ? AND seen_at IS NULL",
        (_now(), member_id),
    )
