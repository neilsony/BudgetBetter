"""The Household pages. Plain server-rendered forms, per ADR-0006.

Every write goes through `core.db.writing`, which takes SQLite's write lock up
front — almost everything here reads then writes, and a deferred transaction
cannot retry that. See ADR-0018.
"""

import datetime as dt
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from budgetbetter.config import get_settings
from budgetbetter.core.db import writing
from budgetbetter.deps import get_connection
from budgetbetter.household import db as household_db
from budgetbetter.household import disputes as disputes_mod
from budgetbetter.household import ledger, notify
from budgetbetter.household.auth import (
    SESSION_COOKIE,
    csrf_token,
    current_member,
    hash_secret,
    new_session_token,
    require_member,
    require_owner,
    verify_csrf,
    verify_secret,
)
from budgetbetter.household.models import LedgerLine, Member
from budgetbetter.templating import TEMPLATES

router = APIRouter(prefix="/household")

SPLIT_LABELS = {
    "equal_all": "Split equally with everyone",
    "equal_selected": "Split equally with some people",
    "custom": "Custom amounts",
    "reimbursement": "Full reimbursement",
    "rent": "Rent",
    "resolution": "Dispute resolution",
}


def to_cents(raw: str) -> int:
    """Dollars as typed into a form, as an exact number of cents."""
    try:
        value = Decimal(str(raw).strip().replace("$", "").replace(",", "") or "0")
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail=f"{raw!r} is not an amount.") from exc
    return int((value * 100).quantize(Decimal("1")))


def _redirect(to: str) -> RedirectResponse:
    return RedirectResponse(to, status_code=303)


def _context(
    request: Request,
    connection,
    member: Member | None,
    *,
    active_tab: str = "household",
    **extra,
) -> dict:
    return {
        "active_tab": active_tab,
        "member": member,
        "is_owner": bool(member and member.is_owner),
        "csrf": csrf_token(request),
        "unseen": household_db.unseen_count(connection, member.id) if member else 0,
        "pending_disputes": len(household_db.list_disputes(connection, pending_only=True)),
        **extra,
    }


def _lines_for(connection, me_id: int) -> list[LedgerLine]:
    """Every ledger row this Member is on, either side."""
    members = household_db.members_by_id(connection)
    pending = household_db.disputes_by_share(connection)
    lines: list[LedgerLine] = []
    for expense in household_db.list_expenses(connection):
        if expense.is_void:
            continue
        for share in expense.shares:
            mine_owed = share.member_id == me_id and expense.payer_id != me_id
            mine_owed_to_me = expense.payer_id == me_id and share.member_id != me_id
            if not (mine_owed or mine_owed_to_me):
                continue
            other_id = expense.payer_id if mine_owed else share.member_id
            other = members.get(other_id)
            if other is None:
                continue
            lines.append(
                LedgerLine(
                    share=share,
                    expense=expense,
                    counterparty=other,
                    owed_by_me=mine_owed,
                    dispute=pending.get(share.id),
                )
            )
    return lines


# --- Getting in ------------------------------------------------------------


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, connection=Depends(get_connection)):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="household_register.html",
        context=_context(
            request,
            connection,
            None,
            first_account=not household_db.count_members(connection),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    pin: str = Form(""),
    connection=Depends(get_connection),
):
    """Name, email and the House PIN. The first account ever created is the
    Owner; every one after it is an ordinary Member."""
    name, email = name.strip(), email.strip().lower()
    if not name or not email or len(password) < 8:
        return _redirect("/household/register?error=A+name%2C+an+email+and+8%2B+characters.")

    with writing(connection):
        first = not household_db.count_members(connection)
        if first:
            # Seed the PIN from the environment so the house has one to share;
            # the Owner changes it in the UI from here on.
            seeded = get_settings().household_pin
            if seeded:
                household_db.set_pin_hash(connection, hash_secret(seeded))
        elif not verify_secret(pin, household_db.get_pin_hash(connection)):
            return _redirect("/household/register?error=That+House+PIN+is+not+right.")

        if household_db.get_member_by_email(connection, email):
            return _redirect("/household/register?error=That+email+is+already+registered.")

        member_id = household_db.create_member(
            connection,
            name=name,
            email=email,
            password_hash=hash_secret(password),
            role="owner" if first else "member",
        )
        household_db.record_event(
            connection,
            actor_id=member_id,
            entity="member",
            entity_id=member_id,
            action="registered",
            after={"name": name, "email": email, "role": "owner" if first else "member"},
        )
        token = new_session_token()
        household_db.create_session(connection, token=token, member_id=member_id)

    response = _redirect("/household")
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30
    )
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, connection=Depends(get_connection)):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="household_login.html",
        context=_context(request, connection, None, error=request.query_params.get("error")),
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    connection=Depends(get_connection),
):
    row = household_db.get_member_by_email(connection, email)
    if not row or not verify_secret(password, row["password_hash"]):
        return _redirect("/household/login?error=That+email+and+password+do+not+match.")

    token = new_session_token()
    with writing(connection):
        household_db.create_session(connection, token=token, member_id=row["id"])

    response = _redirect("/household")
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30
    )
    return response


@router.post("/logout")
def logout(request: Request, connection=Depends(get_connection)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with writing(connection):
            household_db.delete_session(connection, token)
    response = _redirect("/household/login")
    response.delete_cookie(SESSION_COOKIE)
    return response


# --- The dashboard ---------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def dashboard(
    request: Request,
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    members = household_db.members_by_id(connection)
    pairs = [(line.share, line.expense) for line in _lines_for(connection, member.id)]
    balances = ledger.balances(pairs, member.id, members)
    owe, owed = ledger.totals(balances)

    lines = _lines_for(connection, member.id)
    live = [line for line in lines if line.share.counts]
    disputed = [line for line in lines if line.share.is_disputed]
    awaiting = [
        line for line in lines if line.share.is_claimed and line.expense.payer_id == member.id
    ]

    return TEMPLATES.TemplateResponse(
        request=request,
        name="household.html",
        context=_context(
            request,
            connection,
            member,
            balances=balances,
            total_owed=owe,
            total_owed_to_me=owed,
            lines=sorted(live, key=lambda line: line.expense.incurred_on, reverse=True),
            disputed=disputed,
            awaiting=awaiting,
            members=members,
            notifications=household_db.list_notifications(connection, member.id, limit=12),
        ),
    )


@router.get("/history", response_class=HTMLResponse)
def history(
    request: Request,
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    """Everything, settled included. Nothing vanishes, it just moves here."""
    with writing(connection):
        household_db.mark_notifications_seen(connection, member.id)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="household_history.html",
        context=_context(
            request,
            connection,
            member,
            active_tab="history",
            expenses=household_db.list_expenses(connection),
            members=household_db.members_by_id(connection),
            split_labels=SPLIT_LABELS,
        ),
    )


# --- Expenses --------------------------------------------------------------


@router.get("/expenses/new", response_class=HTMLResponse)
def new_expense_page(
    request: Request,
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="household_expense_new.html",
        context=_context(
            request,
            connection,
            member,
            active_members=household_db.list_members(connection, active_only=True),
            today=dt.date.today().isoformat(),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/expenses")
async def create_expense(
    request: Request,
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    form = await request.form()
    verify_csrf(request, form.get("csrf"))

    description = str(form.get("description", "")).strip()
    mode = str(form.get("split_mode", "equal_all"))
    if not description:
        return _redirect("/household/expenses/new?error=Give+it+a+reason.")
    if mode not in ledger.SPLIT_MODES:
        return _redirect("/household/expenses/new?error=Pick+how+to+split+it.")

    selected = [int(v) for v in form.getlist("member_ids")]
    custom = {
        int(key.removeprefix("custom_")): to_cents(str(value))
        for key, value in form.items()
        if key.startswith("custom_") and str(value).strip()
    }
    total_cents = (
        sum(custom.values()) if mode == "custom" else to_cents(str(form.get("amount", "0")))
    )
    if total_cents <= 0:
        return _redirect("/household/expenses/new?error=An+amount+is+needed.")

    if mode == "equal_all":
        selected = [m.id for m in household_db.list_members(connection, active_only=True)]

    try:
        incurred_on = dt.date.fromisoformat(str(form.get("incurred_on")) or "")
    except ValueError:
        incurred_on = dt.date.today()

    try:
        amounts = ledger.shares_for(
            mode,
            total_cents=total_cents,
            member_ids=selected,
            payer_id=member.id,
            custom_cents=custom,
        )
    except ledger.SplitError as exc:
        return _redirect(f"/household/expenses/new?error={str(exc).replace(' ', '+')}")

    with writing(connection):
        expense_id = household_db.create_expense(
            connection,
            payer_id=member.id,
            created_by=member.id,
            description=description,
            total_cents=total_cents,
            kind="general",
            split_mode=mode,
            incurred_on=incurred_on,
            share_amounts=amounts,
        )
        event_id = household_db.record_event(
            connection,
            actor_id=member.id,
            entity="expense",
            entity_id=expense_id,
            action="created",
            after={"description": description, "total_cents": total_cents, "split_mode": mode},
        )
        expense = household_db.get_expense(connection, expense_id)
        notify.expense_created(connection, expense, member.id, event_id)

    return _redirect(f"/household/expenses/{expense_id}")


@router.get("/expenses/{expense_id}", response_class=HTMLResponse)
def expense_page(
    expense_id: int,
    request: Request,
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    expense = household_db.get_expense(connection, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="No such expense.")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="household_expense.html",
        context=_context(
            request,
            connection,
            member,
            expense=expense,
            members=household_db.members_by_id(connection),
            pending=household_db.disputes_by_share(connection),
            timeline=household_db.events_for(connection, "expense", expense_id),
            split_labels=SPLIT_LABELS,
            error=request.query_params.get("error"),
        ),
    )


@router.post("/expenses/{expense_id}/edit")
def edit_expense(
    expense_id: int,
    request: Request,
    csrf: str = Form(""),
    description: str = Form(...),
    amount: str = Form(""),
    incurred_on: str = Form(""),
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    """Fix a typo, while nothing has been paid or disputed.

    The total re-splits equally over whoever is already on the Expense. A
    custom split is left alone, because there is no honest way to spread a new
    total over amounts that were typed in one at a time — delete it and add it
    again instead.
    """
    verify_csrf(request, csrf)
    expense = household_db.get_expense(connection, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="No such expense.")
    if expense.payer_id != member.id and expense.created_by != member.id:
        raise HTTPException(status_code=403, detail="Only the sender can edit this.")
    if expense.locked:
        return _redirect(
            f"/household/expenses/{expense_id}"
            "?error=Someone+has+already+paid+or+disputed+this%2C+so+it+can+no+longer+be+edited."
        )

    try:
        when = dt.date.fromisoformat(incurred_on)
    except ValueError:
        when = expense.incurred_on

    total_cents = expense.total_cents
    amounts = {share.member_id: share.amount_cents for share in expense.shares}
    if amount.strip() and expense.split_mode != "custom":
        total_cents = to_cents(amount)
        if total_cents <= 0:
            return _redirect(f"/household/expenses/{expense_id}?error=An+amount+is+needed.")
        amounts = ledger.allocate_equally(total_cents, list(amounts), expense.payer_id)

    with writing(connection):
        household_db.update_expense(
            connection,
            expense_id,
            description=description.strip() or expense.description,
            total_cents=total_cents,
            incurred_on=when,
            share_amounts=amounts,
        )
        event_id = household_db.record_event(
            connection,
            actor_id=member.id,
            entity="expense",
            entity_id=expense_id,
            action="edited",
            before={
                "description": expense.description,
                "total_cents": expense.total_cents,
                "incurred_on": expense.incurred_on.isoformat(),
            },
            after={
                "description": description.strip() or expense.description,
                "total_cents": total_cents,
                "incurred_on": when.isoformat(),
            },
        )
        notify.expense_changed(
            connection,
            household_db.get_expense(connection, expense_id),
            "edited",
            member.id,
            event_id,
        )
    return _redirect(f"/household/expenses/{expense_id}")


@router.post("/expenses/{expense_id}/void")
def void_expense(
    expense_id: int,
    request: Request,
    csrf: str = Form(""),
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    """Delete an Expense — available only while nothing has been paid.

    Once someone has settled, the money has genuinely moved and the ledger
    cannot honestly unwind it; the remedy is a corrective Expense the other
    way. See ADR-0016.
    """
    verify_csrf(request, csrf)
    expense = household_db.get_expense(connection, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="No such expense.")
    if expense.payer_id != member.id and expense.created_by != member.id:
        raise HTTPException(status_code=403, detail="Only the sender can delete this.")
    if expense.locked:
        return _redirect(
            f"/household/expenses/{expense_id}"
            "?error=Someone+has+already+paid+or+disputed+this%2C+so+it+cannot+be+deleted."
        )

    with writing(connection):
        household_db.void_expense(connection, expense_id, member.id)
        event_id = household_db.record_event(
            connection,
            actor_id=member.id,
            entity="expense",
            entity_id=expense_id,
            action="voided",
            before={"description": expense.description, "total_cents": expense.total_cents},
        )
        notify.expense_changed(connection, expense, "deleted", member.id, event_id)
    return _redirect("/household")


# --- Rent ------------------------------------------------------------------


@router.post("/rent")
def request_rent(
    request: Request,
    csrf: str = Form(""),
    payer_id: int = Form(...),
    confirm: str = Form(""),
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    """One button, no amounts typed. Shares come verbatim from the Rent table,
    which only the Owner edits. See ADR-0019."""
    verify_csrf(request, csrf)
    amounts = household_db.rent_shares(connection)
    active = {m.id for m in household_db.list_members(connection, active_only=True)}
    amounts = {mid: cents for mid, cents in amounts.items() if mid in active and cents}
    if not amounts:
        return _redirect("/household?error=The+rent+table+is+empty.")

    today = dt.date.today()
    existing = household_db.rent_expense_for_month(connection, today.year, today.month)
    if existing and not confirm:
        return _redirect(
            f"/household/expenses/{existing['id']}"
            "?error=Rent+for+this+month+already+exists.+Raise+it+again+only+if+you+mean+to."
        )

    total_cents = sum(amounts.values())
    description = f"Rent — {today.strftime('%B %Y')}"

    with writing(connection):
        expense_id = household_db.create_expense(
            connection,
            payer_id=payer_id,
            created_by=member.id,
            description=description,
            total_cents=total_cents,
            kind="rent",
            split_mode="rent",
            incurred_on=today,
            share_amounts=amounts,
        )
        event_id = household_db.record_event(
            connection,
            actor_id=member.id,
            entity="expense",
            entity_id=expense_id,
            action="rent_raised",
            after={"total_cents": total_cents, "payer_id": payer_id},
        )
        expense = household_db.get_expense(connection, expense_id)
        notify.expense_created(connection, expense, member.id, event_id)
    return _redirect(f"/household/expenses/{expense_id}")


# --- Shares ----------------------------------------------------------------


def _share_and_expense(connection, share_id: int):
    share = household_db.get_share(connection, share_id)
    if share is None:
        raise HTTPException(status_code=404, detail="No such share.")
    expense = household_db.get_expense(connection, share.expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="No such expense.")
    return share, expense


@router.post("/shares/{share_id}/claim")
def claim_share(
    share_id: int,
    request: Request,
    csrf: str = Form(""),
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    """"I've sent this." Does not clear the debt — the payer confirms it.

    This exists because one-sided marking makes the payer the sole authority on
    whether they were paid, which is exactly the fact most likely to be wrong.
    See ADR-0016.
    """
    verify_csrf(request, csrf)
    share, expense = _share_and_expense(connection, share_id)
    if share.member_id != member.id:
        raise HTTPException(status_code=403, detail="That is not your share.")
    if share.status != "owed":
        return _redirect(f"/household/expenses/{expense.id}?error=Nothing+to+claim+there.")

    with writing(connection):
        household_db.set_share_status(connection, share_id, "claimed")
        event_id = household_db.record_event(
            connection,
            actor_id=member.id,
            entity="share",
            entity_id=share_id,
            action="claimed",
            before={"status": "owed"},
            after={"status": "claimed"},
        )
        notify.share_claimed(connection, expense, share, member.id, event_id)
    return _redirect(f"/household/expenses/{expense.id}")


@router.post("/shares/{share_id}/paid")
def mark_paid(
    share_id: int,
    request: Request,
    csrf: str = Form(""),
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    """The payer clearing a Share — either outright or confirming a Claim."""
    verify_csrf(request, csrf)
    share, expense = _share_and_expense(connection, share_id)
    if expense.payer_id != member.id:
        raise HTTPException(status_code=403, detail="Only the person owed can mark this paid.")
    if share.status not in ("owed", "claimed"):
        return _redirect(f"/household/expenses/{expense.id}?error=That+share+is+not+outstanding.")

    with writing(connection):
        household_db.set_share_status(connection, share_id, "paid", paid_by=member.id)
        event_id = household_db.record_event(
            connection,
            actor_id=member.id,
            entity="share",
            entity_id=share_id,
            action="marked_paid",
            before={"status": share.status},
            after={"status": "paid"},
        )
        notify.share_settled(connection, expense, share, member.id, event_id)
    return _redirect(f"/household/expenses/{expense.id}")


@router.post("/shares/{share_id}/unmark")
def unmark_share(
    share_id: int,
    request: Request,
    csrf: str = Form(""),
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    """Undo a mark or a claim. Mis-clicks happen; the reversal is logged."""
    verify_csrf(request, csrf)
    share, expense = _share_and_expense(connection, share_id)
    allowed = expense.payer_id == member.id or (
        share.member_id == member.id and share.status == "claimed"
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="That is not yours to undo.")
    if share.status not in ("paid", "claimed"):
        return _redirect(f"/household/expenses/{expense.id}?error=Nothing+to+undo.")

    with writing(connection):
        household_db.set_share_status(connection, share_id, "owed")
        household_db.record_event(
            connection,
            actor_id=member.id,
            entity="share",
            entity_id=share_id,
            action="reverted",
            before={"status": share.status},
            after={"status": "owed"},
        )
    return _redirect(f"/household/expenses/{expense.id}")


@router.post("/shares/{share_id}/dispute")
def dispute_share(
    share_id: int,
    request: Request,
    csrf: str = Form(""),
    reason: str = Form(...),
    member: Member = Depends(require_member),
    connection=Depends(get_connection),
):
    verify_csrf(request, csrf)
    share, expense = _share_and_expense(connection, share_id)
    if share.member_id != member.id:
        raise HTTPException(status_code=403, detail="You can only dispute your own share.")
    if not expense.disputable:
        return _redirect(
            f"/household/expenses/{expense.id}?error=Rent+and+dispute+resolutions+cannot+be+disputed."
        )
    if share.status not in ("owed", "claimed"):
        return _redirect(f"/household/expenses/{expense.id}?error=That+share+is+not+outstanding.")
    if not reason.strip():
        return _redirect(f"/household/expenses/{expense.id}?error=A+dispute+needs+a+reason.")

    with writing(connection):
        household_db.set_share_status(connection, share_id, "disputed")
        dispute_id = household_db.raise_dispute(
            connection, share_id=share_id, raised_by=member.id, reason=reason.strip()
        )
        event_id = household_db.record_event(
            connection,
            actor_id=member.id,
            entity="share",
            entity_id=share_id,
            action="disputed",
            before={"status": share.status},
            after={"status": "disputed", "dispute_id": dispute_id, "reason": reason.strip()},
        )
        notify.dispute_raised(connection, expense, share, reason.strip(), member.id, event_id)
    return _redirect(f"/household/expenses/{expense.id}")


@router.post("/shares/{share_id}/write-off")
def write_off(
    share_id: int,
    request: Request,
    csrf: str = Form(""),
    reason: str = Form(""),
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    """Forgive a debt, so a departed Member's dead balance stops sitting on
    someone's dashboard forever."""
    verify_csrf(request, csrf)
    share, expense = _share_and_expense(connection, share_id)
    if not share.counts:
        return _redirect(f"/household/expenses/{expense.id}?error=Nothing+outstanding+to+write+off.")

    with writing(connection):
        household_db.write_off_share(
            connection, share_id=share_id, by_member_id=owner.id, reason=reason.strip() or None
        )
        event_id = household_db.record_event(
            connection,
            actor_id=owner.id,
            entity="share",
            entity_id=share_id,
            action="written_off",
            before={"status": share.status, "amount_cents": share.amount_cents},
            after={"written_off": True, "reason": reason.strip() or None},
        )
        notify.debt_written_off(connection, expense, share, owner.id, event_id)
    return _redirect(f"/household/expenses/{expense.id}")


# --- Disputes --------------------------------------------------------------


@router.get("/disputes", response_class=HTMLResponse)
def disputes_page(
    request: Request,
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    pending = household_db.list_disputes(connection, pending_only=True)
    rows = []
    for dispute in pending:
        share = household_db.get_share(connection, dispute.share_id)
        expense = household_db.get_expense(connection, share.expense_id) if share else None
        if share and expense:
            rows.append({"dispute": dispute, "share": share, "expense": expense})
    return TEMPLATES.TemplateResponse(
        request=request,
        name="household_disputes.html",
        context=_context(
            request,
            connection,
            owner,
            active_tab="disputes",
            rows=rows,
            members=household_db.members_by_id(connection),
            resolved=household_db.list_disputes(connection)[:25],
        ),
    )


@router.post("/disputes/{dispute_id}/resolve")
def resolve_dispute(
    dispute_id: int,
    request: Request,
    csrf: str = Form(""),
    outcome: str = Form(...),
    note: str = Form(""),
    amended: str = Form(""),
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    """Uphold, deny or amend. The Owner may resolve a Dispute on their own
    Share — the timeline says so, and transparency is the check. See ADR-0017.
    """
    verify_csrf(request, csrf)
    amended_cents = to_cents(amended) if outcome == "amended" and amended.strip() else None

    try:
        with writing(connection):
            result = disputes_mod.resolve(
                connection,
                dispute_id,
                outcome=outcome,
                resolver_id=owner.id,
                note=note.strip() or None,
                amended_cents=amended_cents,
            )
            dispute = household_db.get_dispute(connection, dispute_id)
            share = household_db.get_share(connection, dispute.share_id)
            notify.dispute_resolved(
                connection,
                result.expense,
                share,
                result.outcome,
                result.touched_member_ids,
                owner.id,
            )
    except disputes_mod.DisputeError as exc:
        return _redirect(f"/household/disputes?error={str(exc).replace(' ', '+')}")
    return _redirect("/household/disputes")


# --- The Owner's desk ------------------------------------------------------


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="household_admin.html",
        context=_context(
            request,
            connection,
            owner,
            active_tab="admin",
            all_members=household_db.list_members(connection),
            rent=household_db.rent_shares(connection),
            rent_total=sum(household_db.rent_shares(connection).values()),
            events=household_db.list_events(connection, limit=100),
            members=household_db.members_by_id(connection),
            has_pin=bool(household_db.get_pin_hash(connection)),
            notice=request.query_params.get("notice"),
        ),
    )


@router.post("/admin/rent")
async def save_rent(
    request: Request,
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    form = await request.form()
    verify_csrf(request, form.get("csrf"))
    with writing(connection):
        for member in household_db.list_members(connection):
            raw = str(form.get(f"rent_{member.id}", "")).strip()
            if raw:
                household_db.set_rent_share(connection, member.id, to_cents(raw))
            else:
                household_db.clear_rent_share(connection, member.id)
        household_db.record_event(
            connection,
            actor_id=owner.id,
            entity="rent_share",
            entity_id=0,
            action="updated",
            after=household_db.rent_shares(connection),
        )
    return _redirect("/household/admin?notice=Rent+table+saved.")


@router.post("/admin/pin")
def change_pin(
    request: Request,
    csrf: str = Form(""),
    pin: str = Form(...),
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    verify_csrf(request, csrf)
    if len(pin.strip()) < 4:
        return _redirect("/household/admin?notice=A+PIN+needs+at+least+4+characters.")
    with writing(connection):
        household_db.set_pin_hash(connection, hash_secret(pin.strip()))
        household_db.record_event(
            connection,
            actor_id=owner.id,
            entity="house_settings",
            entity_id=1,
            action="pin_changed",
        )
    return _redirect("/household/admin?notice=House+PIN+changed.")


@router.post("/admin/members/{member_id}/unregister")
def unregister_member(
    member_id: int,
    request: Request,
    csrf: str = Form(""),
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    """They leave every split picker and other Members' view, but stay named on
    live Shares and keep their whole history. Never deleted. See ADR-0013."""
    verify_csrf(request, csrf)
    target = household_db.get_member(connection, member_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No such member.")
    leaving = target.is_active
    with writing(connection):
        household_db.set_left_on(connection, member_id, dt.date.today() if leaving else None)
        household_db.record_event(
            connection,
            actor_id=owner.id,
            entity="member",
            entity_id=member_id,
            action="unregistered" if leaving else "reinstated",
            after={"left_on": dt.date.today().isoformat() if leaving else None},
        )
    return _redirect("/household/admin?notice=Saved.")


# Re-exported so `app.py` can guard the Plaid-backed routes with it.
__all__ = ["router", "require_owner", "current_member"]
