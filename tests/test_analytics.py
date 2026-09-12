import datetime as dt


from budgetbetter.budgeting.analytics import category_totals, trend_series
from budgetbetter.budgeting.buckets import SEED_RULES
from budgetbetter.budgeting.sync import SyncPage, apply_sync_page

from conftest import raw_txn

GROCERIES = dict(primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_GROCERIES")
RESTAURANT = dict(primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_RESTAURANT")
WAGES = dict(primary="INCOME", detailed="INCOME_WAGES")
CARD_PAYMENT = dict(primary="LOAN_PAYMENTS", detailed="LOAN_PAYMENTS_CREDIT_CARD_PAYMENT")


def store(conn, item_id, *raws):
    apply_sync_page(conn, item_id, SyncPage(added=list(raws), next_cursor="c"), SEED_RULES)


class TestSpendingTotals:
    def test_spending_sums_across_every_account(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", account_id="acc-chequing", amount=50.0, **GROCERIES),
            raw_txn("t2", account_id="acc-visa", amount=30.0, **RESTAURANT),
            raw_txn("t3", account_id="acc-mastercard", amount=20.0, **GROCERIES),
        )
        assert category_totals(conn).total_spending == 100.0

    def test_each_bucket_gets_its_own_total(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", amount=50.0, **GROCERIES),
            raw_txn("t2", amount=30.0, **GROCERIES),
            raw_txn("t3", amount=20.0, **RESTAURANT),
        )
        summary = category_totals(conn)
        assert summary.by_bucket["groceries"] == 80.0
        assert summary.by_bucket["eating_out"] == 20.0

    def test_a_refund_reduces_its_buckets_total(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", amount=50.0, **GROCERIES),
            raw_txn("t2", amount=-20.0, **GROCERIES),
        )
        assert category_totals(conn).by_bucket["groceries"] == 30.0


class TestNonSpending:
    def test_a_credit_card_payment_is_not_counted_as_spending(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", account_id="acc-visa", amount=200.0, **GROCERIES),
            raw_txn(
                "t2",
                account_id="acc-chequing",
                amount=200.0,
                merchant_name="RBC VISA PAYMENT",
                **CARD_PAYMENT,
            ),
        )
        summary = category_totals(conn)
        assert summary.total_spending == 200.0
        assert "transfers" not in summary.by_bucket

    def test_income_is_reported_separately_and_never_nets_off_spending(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", amount=100.0, **GROCERIES),
            raw_txn("t2", amount=-2400.0, **WAGES),
        )
        summary = category_totals(conn)
        assert summary.total_spending == 100.0
        assert summary.total_income == 2400.0
        assert "income" not in summary.by_bucket


class TestFilters:
    def test_totals_can_be_narrowed_to_one_account(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", account_id="acc-visa", amount=50.0, **GROCERIES),
            raw_txn("t2", account_id="acc-chequing", amount=30.0, **GROCERIES),
        )
        assert category_totals(conn, account_id="acc-visa").total_spending == 50.0

    def test_totals_respect_a_date_range(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", date=dt.date(2026, 8, 1), amount=50.0, **GROCERIES),
            raw_txn("t2", date=dt.date(2026, 7, 1), amount=30.0, **GROCERIES),
        )
        summary = category_totals(conn, start=dt.date(2026, 8, 1), end=dt.date(2026, 8, 31))
        assert summary.total_spending == 50.0


class TestTrends:
    def test_monthly_spending_is_grouped_by_month(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", date=dt.date(2026, 7, 5), amount=100.0, **GROCERIES),
            raw_txn("t2", date=dt.date(2026, 7, 20), amount=50.0, **GROCERIES),
            raw_txn("t3", date=dt.date(2026, 8, 3), amount=70.0, **GROCERIES),
        )
        points = trend_series(conn, "month", periods=2, today=dt.date(2026, 8, 28))
        assert [p.spending for p in points] == [150.0, 70.0]

    def test_weekly_spending_is_grouped_by_week_starting_monday(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", date=dt.date(2026, 8, 24), amount=40.0, **GROCERIES),
            raw_txn("t2", date=dt.date(2026, 8, 28), amount=60.0, **GROCERIES),
            raw_txn("t3", date=dt.date(2026, 8, 18), amount=25.0, **GROCERIES),
        )
        points = trend_series(conn, "week", periods=2, today=dt.date(2026, 8, 28))
        assert [p.spending for p in points] == [25.0, 100.0]

    def test_a_period_with_no_spending_still_appears_as_zero(self, conn, linked_item):
        store(conn, linked_item, raw_txn("t1", date=dt.date(2026, 8, 3), amount=70.0, **GROCERIES))
        points = trend_series(conn, "month", periods=3, today=dt.date(2026, 8, 28))
        assert [p.spending for p in points] == [0.0, 0.0, 70.0]

    def test_transfers_are_excluded_from_the_trend(self, conn, linked_item):
        store(
            conn,
            linked_item,
            raw_txn("t1", date=dt.date(2026, 8, 3), amount=70.0, **GROCERIES),
            raw_txn("t2", date=dt.date(2026, 8, 4), amount=500.0, **CARD_PAYMENT),
        )
        points = trend_series(conn, "month", periods=1, today=dt.date(2026, 8, 28))
        assert points[0].spending == 70.0
