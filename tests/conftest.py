import datetime as dt

import pytest

from budgetbetter.core import db


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    db.initialise(connection)
    yield connection
    connection.close()


@pytest.fixture
def linked_item(conn):
    """An Item with the four RBC Accounts already stored."""
    db.upsert_item(
        conn,
        item_id="item-rbc",
        institution_id="ins_rbc",
        institution_name="Royal Bank of Canada",
        access_token_encrypted="ciphertext",
    )
    for account_id, name, type_, subtype, mask in [
        ("acc-chequing", "Day to Day Banking", "depository", "checking", "1234"),
        ("acc-savings", "eSavings", "depository", "savings", "5678"),
        ("acc-visa", "RBC Visa", "credit", "credit card", "4321"),
        ("acc-mastercard", "RBC Mastercard", "credit", "credit card", "8765"),
    ]:
        db.upsert_account(
            conn,
            account_id=account_id,
            item_id="item-rbc",
            name=name,
            official_name=None,
            mask=mask,
            type=type_,
            subtype=subtype,
        )
    return "item-rbc"


@pytest.fixture
def investing_item(conn):
    """A Wealthsimple Item with one investment Account."""
    db.upsert_item(
        conn,
        item_id="item-ws",
        institution_id="ins_wealthsimple",
        institution_name="Wealthsimple",
        access_token_encrypted="ciphertext",
        kind="investing",
    )
    db.upsert_account(
        conn,
        account_id="acc-tfsa",
        item_id="item-ws",
        name="TFSA",
        official_name=None,
        mask="9012",
        type="investment",
        subtype="tfsa",
    )
    return "item-ws"


@pytest.fixture
def second_investing_item(conn):
    """A second investing Item, to prove one Refresh cannot clear another's."""
    db.upsert_item(
        conn,
        item_id="item-other",
        institution_id="ins_other",
        institution_name="Other Broker",
        access_token_encrypted="ciphertext",
        kind="investing",
    )
    db.upsert_account(
        conn,
        account_id="acc-other",
        item_id="item-other",
        name="RRSP",
        official_name=None,
        mask="3456",
        type="investment",
        subtype="rrsp",
    )
    return "item-other"


def raw_txn(
    transaction_id,
    *,
    account_id="acc-chequing",
    date=dt.date(2026, 8, 20),
    name="Some Shop",
    merchant_name=None,
    amount=10.0,
    pending=False,
    primary="GENERAL_MERCHANDISE",
    detailed="GENERAL_MERCHANDISE_OTHER",
):
    """A Transaction shaped the way Plaid returns it."""
    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "date": date,
        "name": name,
        "merchant_name": merchant_name,
        "amount": amount,
        "pending": pending,
        "personal_finance_category": {"primary": primary, "detailed": detailed},
    }
