"""The local web app: Connect once, then Refresh and read the dashboard.

Server-rendered Jinja2 with a little vanilla JavaScript, deliberately with no
build step. See ADR-0006.
"""

import datetime as dt
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from budgetbetter.budgeting import analytics
from budgetbetter.budgeting import db as budgeting_db
from budgetbetter.budgeting import plaid as budgeting_plaid
from budgetbetter.budgeting.buckets import BUCKET_LABELS, BUCKETS
from budgetbetter.budgeting.schedule import next_payday
from budgetbetter.budgeting.sync import refresh_item
from budgetbetter.config import get_settings
from budgetbetter.core import db, plaid_client
from budgetbetter.crypto import TokenCipher
from budgetbetter.deps import get_connection
from budgetbetter.household import db as household_db
from budgetbetter.household.auth import require_owner
from budgetbetter.household.models import Member
from budgetbetter.household.routes import router as household_router
from budgetbetter.investing import db as investing_db
from budgetbetter.investing import plaid as investing_plaid
from budgetbetter.investing import portfolio
from budgetbetter.investing.sync import refresh_investments
from budgetbetter.templating import TEMPLATES


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the schema once, not on every request.

    It used to run from the request-scoped connection dependency, which meant
    every page load took the write lock to do nothing. See ADR-0018.
    """
    connection = db.connect(get_settings().database_path)
    try:
        db.initialise(connection)
    finally:
        connection.close()
    yield


app = FastAPI(title="BudgetBetter", lifespan=lifespan)

# The stylesheet, the shared scripts and the self-hosted font. Still no build
# step — a stylesheet is not a build. See ADR-0006 and ADR-0020.
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).with_name("static"))),
    name="static",
)

RANGES = {
    "30d": "Last 30 days",
    "month": "This month",
    "90d": "Last 90 days",
    "year": "This year",
    "all": "All time",
}

ITEM_KINDS = ("budgeting", "investing")


def date_range(key: str, today: dt.date | None = None) -> tuple[dt.date | None, dt.date | None]:
    today = today or dt.date.today()
    if key == "month":
        return today.replace(day=1), today
    if key == "90d":
        return today - dt.timedelta(days=89), today
    if key == "year":
        return today.replace(month=1, day=1), today
    if key == "all":
        return None, None
    return today - dt.timedelta(days=29), today


def _cipher() -> TokenCipher:
    return TokenCipher(get_settings().encryption_key)


def _nav(connection, member: Member | None = None) -> dict:
    """What the sidebar needs on every page.

    The banking links render for the Owner alone — a Member has no business
    seeing they exist, let alone following one. See ADR-0014.
    """
    return {
        "has_budgeting": bool(db.list_items(connection, kind="budgeting")),
        "has_investing": bool(db.list_items(connection, kind="investing")),
        "is_sandbox": get_settings().is_sandbox,
        "member": member,
        "is_owner": bool(member and member.is_owner),
        "unseen": household_db.unseen_count(connection, member.id) if member else 0,
        "pending_disputes": len(household_db.list_disputes(connection, pending_only=True)),
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    range: str = "30d",
    granularity: str = "month",
    account: str = "",
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    settings = get_settings()
    if settings.missing():
        return TEMPLATES.TemplateResponse(
            request=request,
            name="setup.html",
            context={"missing": settings.missing()},
        )

    if not db.list_items(connection, kind="budgeting"):
        return RedirectResponse("/connect?kind=budgeting", status_code=303)

    range = range if range in RANGES else "30d"
    granularity = granularity if granularity in ("week", "month") else "month"
    start, end = date_range(range)
    account_id = account or None

    summary = analytics.category_totals(
        connection, start=start, end=end, account_id=account_id
    )
    trend = analytics.trend_series(
        connection,
        granularity,
        periods=8 if granularity == "week" else 6,
        account_id=account_id,
    )
    transactions = budgeting_db.list_transactions(
        connection, start=start, end=end, account_id=account_id, limit=300
    )
    budgeting_ids = {
        item["item_id"] for item in db.list_items(connection, kind="budgeting")
    }
    accounts = {
        a.account_id: a
        for a in db.list_accounts(connection)
        if a.item_id in budgeting_ids
    }

    return TEMPLATES.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            **_nav(connection, owner),
            "active_tab": "budgeting",
            "summary": summary,
            "trend": trend,
            "trend_peak": max([p.spending for p in trend] + [1.0]),
            "transactions": transactions,
            "accounts": accounts,
            "account_list": list(accounts.values()),
            "selected_account": account_id,
            "buckets": BUCKETS,
            "bucket_labels": BUCKET_LABELS,
            "ranges": RANGES,
            "selected_range": range,
            "granularity": granularity,
            "last_refreshed": db.last_refreshed_at(connection),
            "next_payday": next_payday(dt.date.today()),
            "is_sandbox": settings.is_sandbox,
        },
    )


@app.get("/investments", response_class=HTMLResponse)
def investments_page(
    request: Request,
    account: str = "",
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    """Holdings and trade history for every investing Item. See ADR-0008."""
    settings = get_settings()
    if settings.missing():
        return TEMPLATES.TemplateResponse(
            request=request, name="setup.html", context={"missing": settings.missing()}
        )

    if not db.list_items(connection, kind="investing"):
        return RedirectResponse("/connect?kind=investing", status_code=303)

    investing_ids = {item["item_id"] for item in db.list_items(connection, kind="investing")}
    accounts = [a for a in db.list_accounts(connection) if a.item_id in investing_ids]
    account_id = account or None

    summary = portfolio.portfolio_summary(connection, account_id=account_id)
    trades = investing_db.list_investment_transactions(connection, account_id=account_id, limit=300)

    return TEMPLATES.TemplateResponse(
        request=request,
        name="investments.html",
        context={
            **_nav(connection, owner),
            "active_tab": "investing",
            "summary": summary,
            "allocation": portfolio.allocation(connection, account_id=account_id),
            "trades": trades,
            "accounts": {a.account_id: a for a in accounts},
            "account_list": accounts,
            "selected_account": account_id,
            "last_refreshed": db.last_refreshed_at(connection),
        },
    )


@app.get("/connect", response_class=HTMLResponse)
def connect_page(
    request: Request,
    kind: str = "budgeting",
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    settings = get_settings()
    if settings.missing():
        return TEMPLATES.TemplateResponse(
            request=request, name="setup.html", context={"missing": settings.missing()}
        )
    kind = kind if kind in ITEM_KINDS else "budgeting"
    return TEMPLATES.TemplateResponse(
        request=request,
        name="connect.html",
        context={
            **_nav(connection, owner),
            "active_tab": kind,
            "kind": kind,
            "items": db.list_items(connection, kind=kind),
        },
    )


@app.post("/api/link-token")
def api_link_token(
    kind: str = Form("budgeting"),
    owner: Member = Depends(require_owner),
):
    settings = get_settings()
    client = plaid_client.build_client(settings)
    kind = kind if kind in ITEM_KINDS else "budgeting"
    try:
        return {"link_token": plaid_client.create_link_token(client, kind=kind)}
    except Exception as exc:  # surfaced in the browser rather than a blank page
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/exchange")
def api_exchange(
    public_token: str = Form(...),
    kind: str = Form("budgeting"),
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    settings = get_settings()
    client = plaid_client.build_client(settings)
    kind = kind if kind in ITEM_KINDS else "budgeting"

    access_token, item_id = plaid_client.exchange_public_token(client, public_token)

    # Store the token before anything else can fail. A public_token is single
    # use, so losing the access_token here would orphan the Item at Plaid and
    # force the owner to link again.
    db.upsert_item(
        connection,
        item_id=item_id,
        institution_id=None,
        institution_name="Bank",
        access_token_encrypted=_cipher().encrypt(access_token),
        kind=kind,
    )
    connection.commit()

    try:
        described = plaid_client.describe_item(client, access_token)
        db.upsert_item(
            connection,
            item_id=item_id,
            institution_id=described.get("institution_id"),
            institution_name=described.get("institution_name") or "Bank",
            access_token_encrypted=_cipher().encrypt(access_token),
            kind=kind,
        )
    except Exception:
        # Only the display name is missing; the connection itself is sound.
        described = {"institution_name": "Bank"}

    for raw_account in plaid_client.fetch_accounts(client, access_token):
        db.upsert_account(
            connection,
            account_id=raw_account["account_id"],
            item_id=item_id,
            name=raw_account.get("name") or "Account",
            official_name=raw_account.get("official_name"),
            mask=raw_account.get("mask"),
            type=str(raw_account.get("type") or "other"),
            subtype=str(raw_account.get("subtype")) if raw_account.get("subtype") else None,
        )
    connection.commit()
    return {"ok": True, "institution": described.get("institution_name"), "kind": kind}


@app.post("/refresh")
def do_refresh(
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    """Pull new and changed Transactions for every budgeting Item. See ADR-0007."""
    settings = get_settings()
    client = plaid_client.build_client(settings)
    cipher = _cipher()

    added = modified = removed = 0
    failures = []
    for item in db.list_items(connection, kind="budgeting"):
        # One Item needing re-authentication must not stop the others.
        try:
            access_token = cipher.decrypt(item["access_token_encrypted"])
            result = refresh_item(
                connection,
                item["item_id"],
                budgeting_plaid.make_page_fetcher(client, access_token),
                budgeting_db.list_rules(connection),
            )
            added += result.added
            modified += result.modified
            removed += result.removed
        except Exception as exc:
            failures.append(f"{item['institution_name'] or item['item_id']}: {exc}")

    query = f"/?refreshed=1&added={added}&modified={modified}&removed={removed}"
    if failures:
        query += "&failed=" + quote("; ".join(failures)[:300])
    return RedirectResponse(query, status_code=303)


@app.post("/investments/refresh")
def do_refresh_investments(
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    """Pull Holdings and trades for every investing Item. See ADR-0008."""
    settings = get_settings()
    client = plaid_client.build_client(settings)
    cipher = _cipher()

    holdings = trades = 0
    failures = []
    for item in db.list_items(connection, kind="investing"):
        try:
            access_token = cipher.decrypt(item["access_token_encrypted"])
            result = refresh_investments(
                connection,
                item["item_id"],
                investing_plaid.make_holdings_fetcher(client, access_token),
                investing_plaid.make_investment_transactions_fetcher(client, access_token),
            )
            holdings += result.holdings
            trades += result.trades
        except Exception as exc:
            failures.append(f"{item['institution_name'] or item['item_id']}: {exc}")

    query = f"/investments?refreshed=1&holdings={holdings}&trades={trades}"
    if failures:
        query += "&failed=" + quote("; ".join(failures)[:300])
    return RedirectResponse(query, status_code=303)


@app.post("/transactions/{transaction_id}/bucket")
def set_bucket(
    transaction_id: str,
    bucket: str = Form(...),
    owner: Member = Depends(require_owner),
    connection=Depends(get_connection),
):
    """Set or clear an Override on one Transaction. See ADR-0003."""
    if bucket not in BUCKETS:
        return JSONResponse({"ok": False, "error": f"Unknown bucket {bucket!r}"}, status_code=400)
    budgeting_db.set_override(connection, transaction_id, bucket)
    return {"ok": True, "bucket": bucket}


app.include_router(household_router)
