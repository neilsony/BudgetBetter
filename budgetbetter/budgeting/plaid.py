"""Pulling Transactions from Plaid. See ADR-0002 and ADR-0012."""

from plaid.api import plaid_api
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_request_options import TransactionsSyncRequestOptions

from budgetbetter.budgeting.sync import SyncPage
from budgetbetter.config import INITIAL_BACKFILL_DAYS


def make_page_fetcher(client: plaid_api.PlaidApi, access_token: str):
    """A `fetch_page(cursor) -> SyncPage` closure for `sync.refresh_item`."""

    def fetch_page(cursor: str | None) -> SyncPage:
        options = TransactionsSyncRequestOptions(
            include_personal_finance_category=True,
            # Only honoured on an Item's first Refresh; asks for 24 months.
            days_requested=INITIAL_BACKFILL_DAYS,
        )
        # Plaid wants the cursor omitted entirely on the first call, not null.
        arguments = {"access_token": access_token, "options": options}
        if cursor:
            arguments["cursor"] = cursor

        response = client.transactions_sync(TransactionsSyncRequest(**arguments)).to_dict()
        return SyncPage(
            added=response.get("added", []),
            modified=response.get("modified", []),
            removed=[entry["transaction_id"] for entry in response.get("removed", [])],
            next_cursor=response.get("next_cursor", ""),
            has_more=bool(response.get("has_more")),
            accounts=response.get("accounts", []),
        )

    return fetch_page
