import datetime as dt

from budgetbetter.core import db
from budgetbetter.budgeting import db as budgeting_db
from budgetbetter.budgeting.buckets import SEED_RULES
from budgetbetter.budgeting.sync import SyncPage, apply_sync_page

from conftest import raw_txn


def page(*, added=(), modified=(), removed=(), cursor="cursor-1", has_more=False):
    return SyncPage(
        added=list(added),
        modified=list(modified),
        removed=list(removed),
        next_cursor=cursor,
        has_more=has_more,
    )


class TestApplyingAPage:
    def test_added_transactions_are_stored(self, conn, linked_item):
        apply_sync_page(conn, linked_item, page(added=[raw_txn("t1"), raw_txn("t2")]), SEED_RULES)
        assert len(budgeting_db.list_transactions(conn)) == 2

    def test_a_stored_transaction_keeps_its_merchant_and_amount(self, conn, linked_item):
        apply_sync_page(
            conn,
            linked_item,
            page(added=[raw_txn("t1", merchant_name="Loblaws", amount=84.32)]),
            SEED_RULES,
        )
        stored = budgeting_db.list_transactions(conn)[0]
        assert stored.display_merchant == "Loblaws"
        assert stored.amount == 84.32

    def test_a_bucket_is_derived_on_the_way_in(self, conn, linked_item):
        apply_sync_page(
            conn,
            linked_item,
            page(
                added=[
                    raw_txn(
                        "t1",
                        merchant_name="Loblaws",
                        primary="FOOD_AND_DRINK",
                        detailed="FOOD_AND_DRINK_GROCERIES",
                    )
                ]
            ),
            SEED_RULES,
        )
        assert budgeting_db.list_transactions(conn)[0].effective_bucket == "groceries"

    def test_the_cursor_is_advanced(self, conn, linked_item):
        apply_sync_page(conn, linked_item, page(added=[raw_txn("t1")], cursor="cursor-2"), SEED_RULES)
        assert db.get_item(conn, linked_item)["sync_cursor"] == "cursor-2"


class TestIdempotency:
    def test_applying_the_same_page_twice_stores_one_copy(self, conn, linked_item):
        same = page(added=[raw_txn("t1"), raw_txn("t2")])
        apply_sync_page(conn, linked_item, same, SEED_RULES)
        apply_sync_page(conn, linked_item, same, SEED_RULES)
        assert len(budgeting_db.list_transactions(conn)) == 2

    def test_a_pending_transaction_becomes_posted_in_place(self, conn, linked_item):
        apply_sync_page(
            conn, linked_item, page(added=[raw_txn("t1", amount=9.99, pending=True)]), SEED_RULES
        )
        apply_sync_page(
            conn,
            linked_item,
            page(modified=[raw_txn("t1", amount=12.50, pending=False)]),
            SEED_RULES,
        )
        stored = budgeting_db.list_transactions(conn)
        assert len(stored) == 1
        assert stored[0].amount == 12.50
        assert stored[0].pending is False

    def test_a_removed_transaction_disappears(self, conn, linked_item):
        apply_sync_page(conn, linked_item, page(added=[raw_txn("t1"), raw_txn("t2")]), SEED_RULES)
        apply_sync_page(conn, linked_item, page(removed=["t1"]), SEED_RULES)
        assert [t.transaction_id for t in budgeting_db.list_transactions(conn)] == ["t2"]

    def test_removing_a_transaction_we_never_had_is_harmless(self, conn, linked_item):
        apply_sync_page(conn, linked_item, page(removed=["never-seen"]), SEED_RULES)
        assert budgeting_db.list_transactions(conn) == []


class TestOverridesSurviveRefreshes:
    def test_an_override_is_not_overwritten_by_a_modification(self, conn, linked_item):
        apply_sync_page(conn, linked_item, page(added=[raw_txn("t1")]), SEED_RULES)
        budgeting_db.set_override(conn, "t1", "drinking")

        apply_sync_page(
            conn,
            linked_item,
            page(
                modified=[
                    raw_txn(
                        "t1",
                        primary="FOOD_AND_DRINK",
                        detailed="FOOD_AND_DRINK_GROCERIES",
                    )
                ]
            ),
            SEED_RULES,
        )
        stored = budgeting_db.list_transactions(conn)[0]
        assert stored.effective_bucket == "drinking"
        assert stored.bucket == "groceries"


class TestUnknownAccounts:
    def test_a_transaction_on_an_unseen_account_is_still_stored(self, conn, linked_item):
        apply_sync_page(
            conn,
            linked_item,
            page(added=[raw_txn("t1", account_id="acc-brand-new")]),
            SEED_RULES,
        )
        assert len(budgeting_db.list_transactions(conn)) == 1


class TestDates:
    def test_a_date_survives_the_round_trip(self, conn, linked_item):
        apply_sync_page(
            conn, linked_item, page(added=[raw_txn("t1", date=dt.date(2026, 3, 9))]), SEED_RULES
        )
        assert budgeting_db.list_transactions(conn)[0].date == dt.date(2026, 3, 9)
