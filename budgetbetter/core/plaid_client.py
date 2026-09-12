"""The Plaid adapter: the client, and the calls both domains make.

Product-specific fetchers live with their domain — `budgetbetter.budgeting.plaid`
pulls Transactions, `budgetbetter.investing.plaid` pulls Holdings. Keeping the
SDK behind these modules is what lets the Refresh loops be tested without
touching the network. See ADR-0002 and ADR-0012.

Canada matters here: RBC needs the CA country code, and Canadian institutions
do not use OAuth, so no redirect URI has to be registered.
"""

import certifi
import plaid
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products

from budgetbetter.config import Settings

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
