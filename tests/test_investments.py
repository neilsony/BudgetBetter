import datetime as dt

from budgetbetter import db
from budgetbetter.investments import (
    HoldingsSnapshot,
    InvestmentTransactionPage,
    apply_holdings_snapshot,
    apply_investment_transactions,
    parse_investment_transaction,
    parse_security,
)
from budgetbetter.portfolio import portfolio_summary


def security(security_id="sec-vfv", ticker="VFV", name="Vanguard S&P 500", close=142.50):
    return {
        "security_id": security_id,
        "name": name,
        "ticker_symbol": ticker,
        "type": "etf",
        "close_price": close,
        "iso_currency_code": "CAD",
    }


def holding(
    security_id="sec-vfv",
    account_id="acc-tfsa",
    quantity=10.0,
    price=142.50,
    value=1425.0,
    cost_basis=1200.0,
):
    return {
        "account_id": account_id,
        "security_id": security_id,
        "quantity": quantity,
        "institution_price": price,
        "institution_value": value,
        "cost_basis": cost_basis,
        "iso_currency_code": "CAD",
    }


def inv_txn(
    txn_id="itx-1",
    account_id="acc-tfsa",
    security_id="sec-vfv",
    date=dt.date(2026, 8, 3),
    name="Buy VFV",
    quantity=5.0,
    amount=700.0,
    price=140.0,
    fees=0.0,
    type_="buy",
    subtype="buy",
):
    return {
        "investment_transaction_id": txn_id,
        "account_id": account_id,
        "security_id": security_id,
        "date": date,
        "name": name,
        "quantity": quantity,
        "amount": amount,
        "price": price,
        "fees": fees,
        "type": type_,
        "subtype": subtype,
        "iso_currency_code": "CAD",
    }


class TestParsing:
    def test_a_security_keeps_its_ticker_and_price(self):
        parsed = parse_security(security())
        assert parsed.ticker_symbol == "VFV"
        assert parsed.close_price == 142.50

    def test_a_security_with_no_ticker_falls_back_to_its_name(self):
        parsed = parse_security(security(ticker=None, name="Wealthsimple Cash"))
        assert parsed.display_name == "Wealthsimple Cash"

    def test_an_investment_transaction_parses_an_iso_date_string(self):
        parsed = parse_investment_transaction(inv_txn(date="2026-07-14"))
        assert parsed.date == dt.date(2026, 7, 14)


class TestHoldingsSnapshot:
    def test_holdings_and_securities_are_stored(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security()],
                holdings=[holding()],
            ),
        )
        stored = db.list_holdings(conn)
        assert len(stored) == 1
        assert stored[0].security.ticker_symbol == "VFV"

    def test_a_snapshot_replaces_the_previous_one(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(accounts=[], securities=[security()], holdings=[holding(quantity=10)]),
        )
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(accounts=[], securities=[security()], holdings=[holding(quantity=25)]),
        )
        stored = db.list_holdings(conn)
        assert len(stored) == 1
        assert stored[0].quantity == 25

    def test_a_sold_out_position_disappears_from_the_snapshot(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security(), security("sec-xeqt", "XEQT", "iShares All Equity")],
                holdings=[holding(), holding(security_id="sec-xeqt")],
            ),
        )
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(accounts=[], securities=[security()], holdings=[holding()]),
        )
        assert [h.security_id for h in db.list_holdings(conn)] == ["sec-vfv"]

    def test_replacing_a_snapshot_leaves_another_items_holdings_alone(
        self, conn, investing_item, second_investing_item
    ):
        apply_holdings_snapshot(
            conn,
            second_investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security("sec-xeqt", "XEQT", "iShares All Equity")],
                holdings=[holding(security_id="sec-xeqt", account_id="acc-other")],
            ),
        )
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(accounts=[], securities=[security()], holdings=[holding()]),
        )
        assert sorted(h.security_id for h in db.list_holdings(conn)) == ["sec-vfv", "sec-xeqt"]


class TestInvestmentTransactions:
    def test_trades_are_stored(self, conn, investing_item):
        apply_investment_transactions(
            conn,
            investing_item,
            InvestmentTransactionPage(
                securities=[security()],
                transactions=[inv_txn("itx-1"), inv_txn("itx-2")],
            ),
        )
        assert len(db.list_investment_transactions(conn)) == 2

    def test_applying_the_same_page_twice_stores_one_copy(self, conn, investing_item):
        page = InvestmentTransactionPage(securities=[security()], transactions=[inv_txn("itx-1")])
        apply_investment_transactions(conn, investing_item, page)
        apply_investment_transactions(conn, investing_item, page)
        assert len(db.list_investment_transactions(conn)) == 1

    def test_a_corrected_trade_updates_in_place(self, conn, investing_item):
        apply_investment_transactions(
            conn,
            investing_item,
            InvestmentTransactionPage(
                securities=[security()], transactions=[inv_txn("itx-1", amount=700.0)]
            ),
        )
        apply_investment_transactions(
            conn,
            investing_item,
            InvestmentTransactionPage(
                securities=[security()], transactions=[inv_txn("itx-1", amount=712.35)]
            ),
        )
        stored = db.list_investment_transactions(conn)
        assert len(stored) == 1
        assert stored[0].amount == 712.35

    def test_a_trade_is_joined_to_its_security(self, conn, investing_item):
        apply_investment_transactions(
            conn,
            investing_item,
            InvestmentTransactionPage(securities=[security()], transactions=[inv_txn()]),
        )
        assert db.list_investment_transactions(conn)[0].security.ticker_symbol == "VFV"

    def test_a_cash_transaction_with_no_security_is_still_stored(self, conn, investing_item):
        apply_investment_transactions(
            conn,
            investing_item,
            InvestmentTransactionPage(
                securities=[],
                transactions=[inv_txn(security_id=None, name="Deposit", type_="cash")],
            ),
        )
        stored = db.list_investment_transactions(conn)
        assert len(stored) == 1
        assert stored[0].security is None


class TestPortfolioSummary:
    def test_total_value_sums_every_holding(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security(), security("sec-xeqt", "XEQT", "iShares All Equity")],
                holdings=[
                    holding(value=1425.0, cost_basis=1200.0),
                    holding(security_id="sec-xeqt", value=575.0, cost_basis=500.0),
                ],
            ),
        )
        summary = portfolio_summary(conn)
        assert summary.total_value == 2000.0
        assert summary.total_cost_basis == 1700.0
        assert summary.total_gain == 300.0

    def test_gain_percent_is_relative_to_cost_basis(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security()],
                holdings=[holding(value=1200.0, cost_basis=1000.0)],
            ),
        )
        assert portfolio_summary(conn).total_gain_pct == 20.0

    def test_a_holding_with_no_cost_basis_still_counts_toward_value(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security()],
                holdings=[holding(value=1425.0, cost_basis=None)],
            ),
        )
        summary = portfolio_summary(conn)
        assert summary.total_value == 1425.0
        assert summary.total_cost_basis == 0.0

    def test_market_value_falls_back_to_quantity_times_price(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security()],
                holdings=[holding(quantity=4, price=25.0, value=None, cost_basis=None)],
            ),
        )
        assert portfolio_summary(conn).total_value == 100.0

    def test_an_empty_portfolio_reports_zero_rather_than_dividing_by_zero(self, conn):
        summary = portfolio_summary(conn)
        assert summary.total_value == 0.0
        assert summary.total_gain_pct == 0.0
