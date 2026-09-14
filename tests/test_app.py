"""Smoke tests for the pages: enough to catch a broken template or route."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from budgetbetter.budgeting import db as budgeting_db
from budgetbetter.app import app, get_connection
from budgetbetter.budgeting.buckets import SEED_RULES
from budgetbetter.config import get_settings
from budgetbetter.crypto import generate_key
from budgetbetter.budgeting.sync import SyncPage, apply_sync_page

from conftest import raw_txn, sign_in


@pytest.fixture
def client(conn, linked_item, owner, monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "test-client")
    monkeypatch.setenv("PLAID_SECRET", "test-secret")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", generate_key())
    get_settings.cache_clear()

    apply_sync_page(
        conn,
        linked_item,
        SyncPage(
            added=[
                raw_txn(
                    "t1",
                    date=dt.date.today(),
                    merchant_name="Loblaws",
                    amount=84.32,
                    primary="FOOD_AND_DRINK",
                    detailed="FOOD_AND_DRINK_GROCERIES",
                ),
                raw_txn(
                    "t2",
                    date=dt.date.today(),
                    account_id="acc-visa",
                    merchant_name="LCBO",
                    amount=31.50,
                    primary="FOOD_AND_DRINK",
                    detailed="FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR",
                ),
            ],
            next_cursor="c1",
        ),
        SEED_RULES,
    )

    app.dependency_overrides[get_connection] = lambda: conn
    yield TestClient(app, cookies=sign_in(conn, owner))
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_the_dashboard_renders_with_transactions(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Loblaws" in response.text
    assert "Total spending" in response.text


def test_the_dashboard_shows_the_spending_total(client):
    assert "$115.82" in client.get("/").text


def test_the_dashboard_shows_which_account_a_transaction_is_on(client):
    assert "RBC Visa" in client.get("/").text


def test_the_week_toggle_renders(client):
    assert client.get("/?granularity=week").status_code == 200


def test_an_unknown_range_falls_back_instead_of_erroring(client):
    assert client.get("/?range=nonsense").status_code == 200


def test_setting_a_bucket_by_hand_stores_an_override(client, conn):
    response = client.post("/transactions/t1/bucket", data={"bucket": "clothes"})
    assert response.status_code == 200
    assert budgeting_db.list_transactions(conn, account_id="acc-chequing")[0].effective_bucket == "clothes"


def test_the_setup_page_appears_when_settings_are_missing(client, monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "")
    get_settings.cache_clear()
    assert "Finish setting up" in client.get("/").text


def test_an_unknown_bucket_is_rejected_and_leaves_the_override_alone(client, conn):
    client.post("/transactions/t1/bucket", data={"bucket": "clothes"})
    response = client.post("/transactions/t1/bucket", data={"bucket": "not-a-bucket"})
    assert response.status_code == 400
    assert budgeting_db.list_transactions(conn, account_id="acc-chequing")[0].effective_bucket == "clothes"


def test_the_refresh_confirmation_is_hidden_until_the_button_is_clicked(client):
    """The two-step confirm is deliberate friction — it must not start visible."""
    html = client.get("/").text
    assert '<span id="confirmBox" class="confirm" hidden>' in html
    assert "[hidden] { display: none !important; }" in html


@pytest.fixture
def investing_client(conn, investing_item, owner, monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "test-client")
    monkeypatch.setenv("PLAID_SECRET", "test-secret")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", generate_key())
    get_settings.cache_clear()

    from budgetbetter.investing.sync import HoldingsSnapshot, InvestmentTransactionPage
    from budgetbetter.investing.sync import apply_holdings_snapshot, apply_investment_transactions

    securities = [
        {
            "security_id": "sec-vfv",
            "name": "Vanguard S&P 500 Index ETF",
            "ticker_symbol": "VFV",
            "type": "etf",
            "close_price": 142.50,
            "iso_currency_code": "CAD",
        }
    ]
    apply_holdings_snapshot(
        conn,
        investing_item,
        HoldingsSnapshot(
            accounts=[],
            securities=securities,
            holdings=[
                {
                    "account_id": "acc-tfsa",
                    "security_id": "sec-vfv",
                    "quantity": 10.0,
                    "institution_price": 142.50,
                    "institution_value": 1425.0,
                    "cost_basis": 1200.0,
                    "iso_currency_code": "CAD",
                }
            ],
        ),
    )
    apply_investment_transactions(
        conn,
        investing_item,
        InvestmentTransactionPage(
            securities=securities,
            transactions=[
                {
                    "investment_transaction_id": "itx-1",
                    "account_id": "acc-tfsa",
                    "security_id": "sec-vfv",
                    "date": dt.date(2026, 8, 3),
                    "name": "Buy VFV",
                    "quantity": 5.0,
                    "amount": 700.0,
                    "price": 140.0,
                    "fees": 0.0,
                    "type": "buy",
                    "subtype": "buy",
                    "iso_currency_code": "CAD",
                }
            ],
        ),
    )

    app.dependency_overrides[get_connection] = lambda: conn
    yield TestClient(app, cookies=sign_in(conn, owner))
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_the_investments_page_renders_holdings(investing_client):
    response = investing_client.get("/investments")
    assert response.status_code == 200
    assert "VFV" in response.text
    assert "Total value" in response.text


def test_the_investments_page_shows_the_portfolio_value(investing_client):
    assert "$1425.00" in investing_client.get("/investments").text


def test_the_investments_page_shows_unrealised_gain(investing_client):
    assert "$225.00" in investing_client.get("/investments").text


def test_the_investments_page_lists_trade_history(investing_client):
    assert "Trade history" in investing_client.get("/investments").text


def test_the_sidebar_links_both_tabs(investing_client):
    body = investing_client.get("/investments").text
    assert 'href="/"' in body and 'href="/investments"' in body


def test_the_investments_page_redirects_to_connect_when_nothing_is_linked(client):
    response = client.get("/investments", follow_redirects=False)
    assert response.status_code == 303
    assert "kind=investing" in response.headers["location"]
