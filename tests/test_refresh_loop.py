"""The Refresh loop: paging, cursors, and what happens when Plaid misbehaves."""

import pytest

from budgetbetter import db
from budgetbetter.buckets import SEED_RULES
from budgetbetter.sync import SyncPage, apply_sync_page, parse_transaction, refresh_item

from conftest import raw_txn

CARD_PAYMENT = dict(primary="LOAN_PAYMENTS", detailed="LOAN_PAYMENTS_CREDIT_CARD_PAYMENT")


def fetcher(*pages):
    """A fake Plaid, recording the cursor it was called with each time."""
    seen = []
    queue = list(pages)

    def fetch_page(cursor):
        seen.append(cursor)
        return queue.pop(0)

    fetch_page.cursors_seen = seen
    return fetch_page


class TestPaging:
    def test_it_follows_has_more_until_plaid_runs_out(self, conn, linked_item):
        fetch = fetcher(
            SyncPage(added=[raw_txn("t1")], next_cursor="c1", has_more=True),
            SyncPage(added=[raw_txn("t2")], next_cursor="c2", has_more=False),
        )
        result = refresh_item(conn, linked_item, fetch, SEED_RULES)
        assert result.added == 2
        assert fetch.cursors_seen == [None, "c1"]

    def test_the_next_refresh_resumes_from_the_stored_cursor(self, conn, linked_item):
        refresh_item(
            conn, linked_item, fetcher(SyncPage(added=[raw_txn("t1")], next_cursor="c1")), SEED_RULES
        )
        second = fetcher(SyncPage(next_cursor="c2"))
        refresh_item(conn, linked_item, second, SEED_RULES)
        assert second.cursors_seen == ["c1"]

    def test_an_empty_cursor_never_replaces_the_stored_one(self, conn, linked_item):
        """An empty cursor reads as a first call and would re-pull 24 months."""
        refresh_item(
            conn, linked_item, fetcher(SyncPage(added=[raw_txn("t1")], next_cursor="c1")), SEED_RULES
        )
        refresh_item(conn, linked_item, fetcher(SyncPage(next_cursor="")), SEED_RULES)
        assert db.get_item(conn, linked_item)["sync_cursor"] == "c1"


class TestIncompleteRefresh:
    def test_running_out_of_pages_is_an_error_not_a_success(self, conn, linked_item):
        always_more = lambda cursor: SyncPage(added=[raw_txn("t1")], next_cursor="c", has_more=True)
        with pytest.raises(RuntimeError, match="another Refresh"):
            refresh_item(conn, linked_item, always_more, SEED_RULES, max_pages=3)

    def test_an_incomplete_refresh_does_not_look_freshly_refreshed(self, conn, linked_item):
        always_more = lambda cursor: SyncPage(added=[raw_txn("t1")], next_cursor="c", has_more=True)
        with pytest.raises(RuntimeError):
            refresh_item(conn, linked_item, always_more, SEED_RULES, max_pages=2)
        assert db.get_item(conn, linked_item)["last_refreshed_at"] is None


class TestBadDataFromPlaid:
    def test_a_transaction_with_no_date_fails_loudly_naming_itself(self):
        with pytest.raises(ValueError, match="t-broken"):
            parse_transaction(
                {"transaction_id": "t-broken", "account_id": "acc-chequing", "date": None},
                SEED_RULES,
            )


class TestTransferSafetyNet:
    def test_a_card_payment_stays_out_of_spending_even_with_no_rules(self, conn, linked_item):
        """ADR-0004 must hold even if the Rules table is edited or emptied."""
        apply_sync_page(
            conn,
            linked_item,
            SyncPage(added=[raw_txn("t1", amount=500.0, **CARD_PAYMENT)], next_cursor="c"),
            rules=[],
        )
        assert db.list_transactions(conn)[0].effective_bucket == "transfers"


class TestListLimit:
    def test_a_limit_of_zero_returns_nothing_rather_than_everything(self, conn, linked_item):
        apply_sync_page(
            conn, linked_item, SyncPage(added=[raw_txn("t1")], next_cursor="c"), SEED_RULES
        )
        assert db.list_transactions(conn, limit=0) == []
