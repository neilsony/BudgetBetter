"""Pulling Holdings and trades from Plaid. See ADR-0008 and ADR-0012."""

import datetime as dt

from plaid.api import plaid_api
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
from plaid.model.investments_transactions_get_request_options import (
    InvestmentsTransactionsGetRequestOptions,
)

from budgetbetter.config import INITIAL_BACKFILL_DAYS
from budgetbetter.investing.sync import HoldingsSnapshot, InvestmentTransactionPage


def make_holdings_fetcher(client: plaid_api.PlaidApi, access_token: str):
    """A `fetch_holdings() -> HoldingsSnapshot` closure. See ADR-0008."""

    def fetch_holdings() -> HoldingsSnapshot:
        response = client.investments_holdings_get(
            InvestmentsHoldingsGetRequest(access_token=access_token)
        ).to_dict()
        return HoldingsSnapshot(
            accounts=response.get("accounts", []),
            securities=response.get("securities", []),
            holdings=response.get("holdings", []),
        )

    return fetch_holdings


def make_investment_transactions_fetcher(
    client: plaid_api.PlaidApi,
    access_token: str,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    page_size: int = 500,
):
    """A `fetch(offset) -> InvestmentTransactionPage` closure.

    This endpoint is offset-paginated over a date range rather than
    cursor-based, so we ask for the same backfill window as spending.
    """
    end = end or dt.date.today()
    start = start or (end - dt.timedelta(days=INITIAL_BACKFILL_DAYS))

    def fetch(offset: int) -> InvestmentTransactionPage:
        response = client.investments_transactions_get(
            InvestmentsTransactionsGetRequest(
                access_token=access_token,
                start_date=start,
                end_date=end,
                options=InvestmentsTransactionsGetRequestOptions(count=page_size, offset=offset),
            )
        ).to_dict()
        return InvestmentTransactionPage(
            securities=response.get("securities", []),
            transactions=response.get("investment_transactions", []),
            total=int(response.get("total_investment_transactions") or 0),
        )

    return fetch
