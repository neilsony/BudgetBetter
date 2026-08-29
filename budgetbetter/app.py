"""The local web app: Connect once, then Refresh and read the dashboard.

Server-rendered Jinja2 with a little vanilla JavaScript, deliberately with no
build step. See ADR-0006.
"""

import datetime as dt
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from budgetbetter import analytics, db, plaid_client
from budgetbetter.buckets import BUCKET_LABELS, BUCKETS
from budgetbetter.config import get_settings
from budgetbetter.crypto import TokenCipher
from budgetbetter.schedule import next_payday
from budgetbetter.sync import refresh_item

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))

app = FastAPI(title="BudgetBetter")

RANGES = {
    "30d": "Last 30 days",
    "month": "This month",
    "90d": "Last 90 days",
    "year": "This year",
    "all": "All time",
}


def get_connection():
    settings = get_settings()
    connection = db.connect(settings.database_path)
    db.initialise(connection)
    try:
        yield connection
    finally:
        connection.close()


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


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    range: str = "30d",
    granularity: str = "month",
    account: str = "",
    connection=Depends(get_connection),
):
    settings = get_settings()
    if settings.missing():
        return TEMPLATES.TemplateResponse(
            request=request,
            name="setup.html",
            context={"missing": settings.missing()},
        )

    if not db.list_items(connection):
        return RedirectResponse("/connect", status_code=303)

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
    transactions = db.list_transactions(
        connection, start=start, end=end, account_id=account_id, limit=300
    )
    accounts = {a.account_id: a for a in db.list_accounts(connection)}

    return TEMPLATES.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
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


@app.get("/connect", response_class=HTMLResponse)
def connect_page(request: Request, connection=Depends(get_connection)):
    settings = get_settings()
    if settings.missing():
        return TEMPLATES.TemplateResponse(
            request=request, name="setup.html", context={"missing": settings.missing()}
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="connect.html",
        context={
            "items": db.list_items(connection),
            "is_sandbox": settings.is_sandbox,
        },
    )


@app.post("/api/link-token")
def api_link_token():
    settings = get_settings()
    client = plaid_client.build_client(settings)
    try:
        return {"link_token": plaid_client.create_link_token(client)}
    except Exception as exc:  # surfaced in the browser rather than a blank page
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/exchange")
def api_exchange(public_token: str = Form(...), connection=Depends(get_connection)):
    settings = get_settings()
    client = plaid_client.build_client(settings)

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
    return {"ok": True, "institution": described.get("institution_name")}


@app.post("/refresh")
def do_refresh(connection=Depends(get_connection)):
    """Pull new and changed Transactions for every Item. See ADR-0007."""
    settings = get_settings()
    client = plaid_client.build_client(settings)
    cipher = _cipher()

    added = modified = removed = 0
    failures = []
    for item in db.list_items(connection):
        # One Item needing re-authentication must not stop the others.
        try:
            access_token = cipher.decrypt(item["access_token_encrypted"])
            result = refresh_item(
                connection,
                item["item_id"],
                plaid_client.make_page_fetcher(client, access_token),
                db.list_rules(connection),
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


@app.post("/transactions/{transaction_id}/bucket")
def set_bucket(
    transaction_id: str,
    bucket: str = Form(...),
    connection=Depends(get_connection),
):
    """Set or clear an Override on one Transaction. See ADR-0003."""
    if bucket not in BUCKETS:
        return JSONResponse({"ok": False, "error": f"Unknown bucket {bucket!r}"}, status_code=400)
    db.set_override(connection, transaction_id, bucket)
    return {"ok": True, "bucket": bucket}
