"""The Plaid adapter: every call to Plaid goes through here.

Keeping the SDK behind one module is what lets the Refresh loop in sync.py be
tested without touching the network. Canada matters here — RBC needs the CA
country code, and Canadian institutions do not use OAuth, so no redirect URI
has to be registered. See ADR-0002.
"""

import datetime as dt

import certifi
import plaid
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_request_options import TransactionsSyncRequestOptions

from budgetbetter.config import INITIAL_BACKFILL_DAYS, Settings
from budgetbetter.investments import HoldingsSnapshot, InvestmentTransactionPage
from budgetbetter.sync import SyncPage

# RBC is Canadian; without CA it will not appear in Link.
COUNTRY_CODES = ["CA", "US"]

# Which Plaid product each kind of Item is linked for. See ADR-0008.
PRODUCTS_FOR_KIND = {
    "budgeting": ["transactions"],
    "investing": ["investments"],
}


def build_client(settings: Settings) -> plaid_api.PlaidApi:
    host = plaid.Environment.Sandbox if settings.is_sandbox else plaid.Environment.Production
    configuration = plaid.Configuration(
        host=host,
        api_key={"clientId": settings.plaid_client_id, "secret": settings.plaid_secret},
    )
    # plaid-python defaults ca_certs to None, which makes urllib3 fall back to the
    # system cert store. On a python.org macOS build that store is empty unless
    # "Install Certificates.command" was run, so point it at certifi explicitly.
    configuration.ssl_ca_cert = certifi.where()
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def create_link_token(
    client: plaid_api.PlaidApi,
    *,
    kind: str = "budgeting",
    user_id: str = "budgetbetter-owner",
) -> str:
    request = LinkTokenCreateRequest(
        client_name="BudgetBetter",
        products=[Products(name) for name in PRODUCTS_FOR_KIND.get(kind, ["transactions"])],
        country_codes=[CountryCode(code) for code in COUNTRY_CODES],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
    )
    return client.link_token_create(request).to_dict()["link_token"]


def exchange_public_token(client: plaid_api.PlaidApi, public_token: str) -> tuple[str, str]:
    """Trade the short-lived token from Link for the Item's long-lived one."""
    response = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    ).to_dict()
    return response["access_token"], response["item_id"]


def describe_item(client: plaid_api.PlaidApi, access_token: str) -> dict:
    """The Institution behind an Item, for display."""
    from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
    from plaid.model.item_get_request import ItemGetRequest

    item = client.item_get(ItemGetRequest(access_token=access_token)).to_dict()["item"]
    institution_id = item.get("institution_id")
    name = None
    if institution_id:
        try:
            institution = client.institutions_get_by_id(
                InstitutionsGetByIdRequest(
                    institution_id=institution_id,
                    country_codes=[CountryCode(code) for code in COUNTRY_CODES],
                )
            ).to_dict()["institution"]
            name = institution.get("name")
        except plaid.ApiException:
            name = None
    return {"item_id": item["item_id"], "institution_id": institution_id, "institution_name": name}


def fetch_accounts(client: plaid_api.PlaidApi, access_token: str) -> list[dict]:
    from plaid.model.accounts_get_request import AccountsGetRequest

    response = client.accounts_get(AccountsGetRequest(access_token=access_token)).to_dict()
    return response.get("accounts", [])


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


# --- Investments -----------------------------------------------------------


def make_holdings_fetcher(client: plaid_api.PlaidApi, access_token: str):
    """A `fetch_holdings() -> HoldingsSnapshot` closure. See ADR-0008."""
    from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest

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
    from plaid.model.investments_transactions_get_request import (
        InvestmentsTransactionsGetRequest,
    )
    from plaid.model.investments_transactions_get_request_options import (
        InvestmentsTransactionsGetRequestOptions,
    )

    end = end or dt.date.today()
    start = start or (end - dt.timedelta(days=INITIAL_BACKFILL_DAYS))

    def fetch(offset: int) -> InvestmentTransactionPage:
        response = client.investments_transactions_get(
            InvestmentsTransactionsGetRequest(
                access_token=access_token,
                start_date=start,
                end_date=end,
                options=InvestmentsTransactionsGetRequestOptions(
                    count=page_size, offset=offset
                ),
            )
        ).to_dict()
        return InvestmentTransactionPage(
            securities=response.get("securities", []),
            transactions=response.get("investment_transactions", []),
            total=int(response.get("total_investment_transactions") or 0),
        )

    return fetch
