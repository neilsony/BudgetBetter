"""Smoke tests for the pages: enough to catch a broken template or route."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from budgetbetter import db
from budgetbetter.app import app, get_connection
from budgetbetter.buckets import SEED_RULES
from budgetbetter.config import get_settings
from budgetbetter.crypto import generate_key
from budgetbetter.sync import SyncPage, apply_sync_page

from conftest import raw_txn


@pytest.fixture
def client(conn, linked_item, monkeypatch):
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
    yield TestClient(app)
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
    assert db.list_transactions(conn, account_id="acc-chequing")[0].effective_bucket == "clothes"


def test_the_setup_page_appears_when_settings_are_missing(client, monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "")
    get_settings.cache_clear()
    assert "Finish setting up" in client.get("/").text


def test_an_unknown_bucket_is_rejected_and_leaves_the_override_alone(client, conn):
    client.post("/transactions/t1/bucket", data={"bucket": "clothes"})
    response = client.post("/transactions/t1/bucket", data={"bucket": "not-a-bucket"})
    assert response.status_code == 400
    assert db.list_transactions(conn, account_id="acc-chequing")[0].effective_bucket == "clothes"


def test_the_refresh_confirmation_is_hidden_until_the_button_is_clicked(client):
    """The two-step confirm is deliberate friction — it must not start visible."""
    html = client.get("/").text
    assert '<span id="confirmBox" class="confirm" hidden>' in html
    assert "[hidden] { display: none !important; }" in html
