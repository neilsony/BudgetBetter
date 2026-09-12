import datetime as dt

from budgetbetter.core import db
from budgetbetter.investing import db as investing_db
from budgetbetter.investing.sync import (
    HoldingsSnapshot,
    InvestmentTransactionPage,
    apply_holdings_snapshot,
    apply_investment_transactions,
    parse_investment_transaction,
    parse_security,
)
from budgetbetter.investing.portfolio import portfolio_summary


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
        stored = investing_db.list_holdings(conn)
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
        stored = investing_db.list_holdings(conn)
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
        assert [h.security_id for h in investing_db.list_holdings(conn)] == ["sec-vfv"]

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
        assert sorted(h.security_id for h in investing_db.list_holdings(conn)) == ["sec-vfv", "sec-xeqt"]


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
        assert len(investing_db.list_investment_transactions(conn)) == 2

    def test_applying_the_same_page_twice_stores_one_copy(self, conn, investing_item):
        page = InvestmentTransactionPage(securities=[security()], transactions=[inv_txn("itx-1")])
        apply_investment_transactions(conn, investing_item, page)
        apply_investment_transactions(conn, investing_item, page)
        assert len(investing_db.list_investment_transactions(conn)) == 1

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
        stored = investing_db.list_investment_transactions(conn)
        assert len(stored) == 1
        assert stored[0].amount == 712.35

    def test_a_trade_is_joined_to_its_security(self, conn, investing_item):
        apply_investment_transactions(
            conn,
            investing_item,
            InvestmentTransactionPage(securities=[security()], transactions=[inv_txn()]),
        )
        assert investing_db.list_investment_transactions(conn)[0].security.ticker_symbol == "VFV"

    def test_a_cash_transaction_with_no_security_is_still_stored(self, conn, investing_item):
        apply_investment_transactions(
            conn,
            investing_item,
            InvestmentTransactionPage(
                securities=[],
                transactions=[inv_txn(security_id=None, name="Deposit", type_="cash")],
            ),
        )
        stored = investing_db.list_investment_transactions(conn)
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


class TestPriceFallback:
    """Wealthsimple reports 0 rather than null when it has no live price, so a
    Holding must fall back to the Security's last close. See ADR-0009."""

    def _snapshot(self, conn, item, **holding_kwargs):
        apply_holdings_snapshot(
            conn,
            item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security(close=188.58)],
                holdings=[holding(**holding_kwargs)],
            ),
        )
        return investing_db.list_holdings(conn)[0]

    def test_a_zero_institution_price_falls_back_to_the_last_close(self, conn, investing_item):
        stored = self._snapshot(conn, investing_item, quantity=2.0, price=0.0, value=0.0)
        assert stored.effective_price == 188.58
        assert stored.market_value == 377.16

    def test_a_zero_institution_value_does_not_zero_the_holding(self, conn, investing_item):
        stored = self._snapshot(conn, investing_item, quantity=1.3464, price=0.0, value=0.0)
        assert stored.market_value > 0

    def test_a_real_institution_price_still_wins_over_the_close(self, conn, investing_item):
        stored = self._snapshot(conn, investing_item, quantity=2.0, price=200.0, value=None)
        assert stored.effective_price == 200.0
        assert stored.market_value == 400.0

    def test_a_real_institution_value_still_wins(self, conn, investing_item):
        stored = self._snapshot(conn, investing_item, quantity=2.0, price=200.0, value=415.0)
        assert stored.market_value == 415.0

    def test_a_fallback_price_is_flagged_as_such(self, conn, investing_item):
        assert self._snapshot(conn, investing_item, price=0.0, value=0.0).price_is_fallback
        assert not self._snapshot(conn, investing_item, price=200.0, value=None).price_is_fallback

    def test_a_holding_with_no_price_anywhere_reports_an_unknown_value(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security(close=None)],
                holdings=[holding(price=0.0, value=0.0)],
            ),
        )
        stored = investing_db.list_holdings(conn)[0]
        assert stored.effective_price is None
        assert stored.market_value == 0.0

    def test_the_portfolio_total_uses_the_fallback_prices(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[
                    security(close=100.0),
                    security("sec-xeqt", "XEQT", "iShares All Equity", close=50.0),
                ],
                holdings=[
                    holding(quantity=2.0, price=0.0, value=0.0, cost_basis=150.0),
                    holding(security_id="sec-xeqt", quantity=4.0, price=0.0, value=0.0,
                            cost_basis=150.0),
                ],
            ),
        )
        summary = portfolio_summary(conn)
        assert summary.total_value == 400.0
        assert summary.total_gain == 100.0

    def test_the_summary_counts_holdings_whose_value_is_unknown(self, conn, investing_item):
        apply_holdings_snapshot(
            conn,
            investing_item,
            HoldingsSnapshot(
                accounts=[],
                securities=[security(close=None)],
                holdings=[holding(price=0.0, value=0.0)],
            ),
        )
        assert portfolio_summary(conn).unpriced_count == 1


class TestCash:
    """Cash sits in the Account's balance, not in a Holding. See ADR-0010."""

    def _snapshot(self, conn, item, balance, holdings, securities=None):
        apply_holdings_snapshot(
            conn,
            item,
            HoldingsSnapshot(
                accounts=[
                    {
                        "account_id": "acc-tfsa",
                        "name": "TFSA",
                        "type": "investment",
                        "subtype": "tfsa",
                        "balances": {"current": balance, "iso_currency_code": "CAD"},
                    }
                ],
                securities=securities if securities is not None else [security(close=100.0)],
                holdings=holdings,
            ),
        )

    def test_the_account_balance_is_stored(self, conn, investing_item):
        self._snapshot(conn, investing_item, 1500.0, [holding(quantity=10.0, price=0.0, value=0.0)])
        assert db.list_accounts(conn)[0].current_balance == 1500.0

    def test_cash_is_the_balance_left_over_after_securities(self, conn, investing_item):
        self._snapshot(conn, investing_item, 1500.0, [holding(quantity=10.0, price=0.0, value=0.0)])
        summary = portfolio_summary(conn)
        assert summary.total_securities == 1000.0
        assert summary.total_cash == 500.0

    def test_total_value_follows_the_broker_balance_not_our_sum(self, conn, investing_item):
        self._snapshot(conn, investing_item, 1500.0, [holding(quantity=10.0, price=0.0, value=0.0)])
        assert portfolio_summary(conn).total_value == 1500.0

    def test_cash_is_excluded_from_gain(self, conn, investing_item):
        self._snapshot(
            conn,
            investing_item,
            1500.0,
            [holding(quantity=10.0, price=0.0, value=0.0, cost_basis=900.0)],
        )
        summary = portfolio_summary(conn)
        # Securities are worth 1000 against a 900 basis; the 500 of cash is not a gain.
        assert summary.total_gain == 100.0

    def test_an_account_with_no_balance_falls_back_to_its_securities(self, conn, investing_item):
        self._snapshot(conn, investing_item, None, [holding(quantity=10.0, price=0.0, value=0.0)])
        summary = portfolio_summary(conn)
        assert summary.total_value == 1000.0
        assert summary.total_cash == 0.0

    def test_a_pure_cash_account_still_appears(self, conn, investing_item):
        self._snapshot(conn, investing_item, 750.0, [])
        summary = portfolio_summary(conn)
        assert summary.total_cash == 750.0
        assert summary.total_value == 750.0
        assert [p.name for p in summary.accounts] == ["TFSA"]

    def test_a_balance_below_the_securities_value_never_reports_negative_cash(
        self, conn, investing_item
    ):
        # Last-close prices can briefly exceed what the broker reports.
        self._snapshot(conn, investing_item, 900.0, [holding(quantity=10.0, price=0.0, value=0.0)])
        assert portfolio_summary(conn).total_cash == 0.0


class TestAllTimeReturn:
    """The broker's headline number: what the account is worth against what was
    ever paid into it. See ADR-0011."""

    def _flow(self, txn_id, amount, subtype, type_="cash"):
        return inv_txn(txn_id, security_id=None, amount=amount, subtype=subtype,
                       type_=type_, quantity=None, price=None)

    def _setup(self, conn, item, balance, flows, cost_basis=900.0):
        apply_holdings_snapshot(
            conn,
            item,
            HoldingsSnapshot(
                accounts=[{
                    "account_id": "acc-tfsa", "name": "TFSA",
                    "type": "investment", "subtype": "tfsa",
                    "balances": {"current": balance, "iso_currency_code": "CAD"},
                }],
                securities=[security(close=100.0)],
                holdings=[holding(quantity=10.0, price=0.0, value=0.0, cost_basis=cost_basis)],
            ),
        )
        apply_investment_transactions(
            conn, item, InvestmentTransactionPage(securities=[], transactions=flows)
        )

    def test_a_deposit_counts_as_money_paid_in(self, conn, investing_item):
        # Plaid signs cash arriving as negative.
        self._setup(conn, investing_item, 1100.0, [self._flow("f1", -1000.0, "deposit")])
        summary = portfolio_summary(conn)
        assert summary.net_contributions == 1000.0
        assert summary.all_time_gain == 100.0

    def test_a_withdrawal_reduces_money_paid_in(self, conn, investing_item):
        self._setup(
            conn, investing_item, 1100.0,
            [self._flow("f1", -1000.0, "deposit"), self._flow("f2", 200.0, "withdrawal")],
        )
        assert portfolio_summary(conn).net_contributions == 800.0

    def test_a_transfer_in_counts_as_money_paid_in(self, conn, investing_item):
        self._setup(
            conn, investing_item, 1100.0,
            [self._flow("f1", -900.0, "deposit"),
             self._flow("f2", -100.0, "transfer", type_="transfer")],
        )
        assert portfolio_summary(conn).net_contributions == 1000.0

    def test_buys_and_sells_are_not_money_paid_in(self, conn, investing_item):
        self._setup(
            conn, investing_item, 1100.0,
            [self._flow("f1", -1000.0, "deposit"),
             inv_txn("f2", amount=500.0, type_="buy", subtype="buy"),
             inv_txn("f3", amount=-300.0, type_="sell", subtype="sell")],
        )
        assert portfolio_summary(conn).net_contributions == 1000.0

    def test_a_dividend_is_a_return_not_a_contribution(self, conn, investing_item):
        # This is what makes the figure match the broker's: a dividend is money
        # the account earned, not money the owner paid in.
        self._setup(
            conn, investing_item, 1100.0,
            [self._flow("f1", -1000.0, "deposit"), self._flow("f2", -50.0, "dividend")],
        )
        summary = portfolio_summary(conn)
        assert summary.net_contributions == 1000.0
        assert summary.all_time_gain == 100.0

    def test_all_time_return_is_relative_to_what_was_paid_in(self, conn, investing_item):
        self._setup(conn, investing_item, 1100.0, [self._flow("f1", -1000.0, "deposit")])
        assert portfolio_summary(conn).all_time_gain_pct == 10.0

    def test_all_time_return_counts_cash_and_realised_gains(self, conn, investing_item):
        # Securities are worth 1000 on a 900 basis, so unrealised gain is 100 —
        # but the account holds 1200, so the all-time gain is 200.
        self._setup(conn, investing_item, 1200.0, [self._flow("f1", -1000.0, "deposit")])
        summary = portfolio_summary(conn)
        assert summary.total_gain == 100.0
        assert summary.all_time_gain == 200.0

    def test_nothing_paid_in_reports_zero_rather_than_dividing_by_zero(self, conn, investing_item):
        self._setup(conn, investing_item, 1100.0, [])
        summary = portfolio_summary(conn)
        assert summary.net_contributions == 0.0
        assert summary.all_time_gain_pct == 0.0
        assert not summary.has_contributions
