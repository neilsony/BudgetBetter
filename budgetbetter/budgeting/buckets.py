"""The Bucket vocabulary and the Rules that seed a fresh database.

Buckets are this project's own spending categories, as opposed to the Plaid
Category that arrives on each Transaction. See CONTEXT.md and ADR-0003.
"""

from budgetbetter.budgeting.models import Rule

GROCERIES = "groceries"
EATING_OUT = "eating_out"
DRINKING = "drinking"
CLOTHES = "clothes"
RENT = "rent"
TRANSPORT = "transport"
UTILITIES = "utilities"
SUBSCRIPTIONS = "subscriptions"
HEALTH = "health"
ENTERTAINMENT = "entertainment"
INCOME = "income"
TRANSFERS = "transfers"
OTHER = "other"

BUCKETS = [
    GROCERIES,
    EATING_OUT,
    DRINKING,
    CLOTHES,
    RENT,
    TRANSPORT,
    UTILITIES,
    SUBSCRIPTIONS,
    HEALTH,
    ENTERTAINMENT,
    INCOME,
    TRANSFERS,
    OTHER,
]

BUCKET_LABELS = {
    GROCERIES: "Groceries",
    EATING_OUT: "Eating out",
    DRINKING: "Drinking",
    CLOTHES: "Clothes",
    RENT: "Rent",
    TRANSPORT: "Transport",
    UTILITIES: "Utilities",
    SUBSCRIPTIONS: "Subscriptions",
    HEALTH: "Health",
    ENTERTAINMENT: "Entertainment",
    INCOME: "Income",
    TRANSFERS: "Transfers",
    OTHER: "Other",
}

# Buckets that are not spending, and so never appear in a spending total.
# See ADR-0004.
NON_SPENDING_BUCKETS = {INCOME, TRANSFERS}

# Plaid Categories that mean money moved between the owner's own Accounts.
# A credit card payment is the important one: the spending was already recorded
# when the card was used, so counting the payment too would double-count it.
INTERNAL_TRANSFER_DETAILED = {
    "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT",
    "TRANSFER_IN_ACCOUNT_TRANSFER",
    "TRANSFER_OUT_ACCOUNT_TRANSFER",
    "TRANSFER_IN_DEPOSIT",
    "TRANSFER_OUT_WITHDRAWAL",
}

INTERNAL_TRANSFER_PRIMARY = {"TRANSFER_IN", "TRANSFER_OUT"}


def _plaid_rules() -> list[tuple[str, str]]:
    """(Plaid Category, Bucket) pairs, detailed before primary."""
    return [
        # Food and drink
        ("FOOD_AND_DRINK_GROCERIES", GROCERIES),
        ("FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR", DRINKING),
        ("FOOD_AND_DRINK_RESTAURANT", EATING_OUT),
        ("FOOD_AND_DRINK_FAST_FOOD", EATING_OUT),
        ("FOOD_AND_DRINK_COFFEE", EATING_OUT),
        ("FOOD_AND_DRINK_VENDING_MACHINES", EATING_OUT),
        ("FOOD_AND_DRINK_OTHER_FOOD_AND_DRINK", EATING_OUT),
        ("FOOD_AND_DRINK", EATING_OUT),
        # Clothing
        ("GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES", CLOTHES),
        # Housing
        ("RENT_AND_UTILITIES_RENT", RENT),
        ("RENT_AND_UTILITIES", UTILITIES),
        # Getting around
        ("TRANSPORTATION", TRANSPORT),
        ("TRAVEL", TRANSPORT),
        # Health
        ("MEDICAL", HEALTH),
        ("PERSONAL_CARE", HEALTH),
        # Leisure
        ("ENTERTAINMENT_TV_AND_MOVIES", SUBSCRIPTIONS),
        ("ENTERTAINMENT_MUSIC_AND_AUDIO", SUBSCRIPTIONS),
        ("ENTERTAINMENT", ENTERTAINMENT),
        ("GENERAL_SERVICES_SUBSCRIPTIONS", SUBSCRIPTIONS),
        # Money in, and money that only moved
        ("INCOME", INCOME),
        ("LOAN_PAYMENTS_CREDIT_CARD_PAYMENT", TRANSFERS),
        ("TRANSFER_IN", TRANSFERS),
        ("TRANSFER_OUT", TRANSFERS),
    ]


def _merchant_rules() -> list[tuple[str, str]]:
    """(merchant keyword, Bucket) pairs for merchants Plaid tends to misfile."""
    return [
        ("lcbo", DRINKING),
        ("the beer store", DRINKING),
        ("wine rack", DRINKING),
        ("netflix", SUBSCRIPTIONS),
        ("spotify", SUBSCRIPTIONS),
        ("uber eats", EATING_OUT),
        ("doordash", EATING_OUT),
        ("skipthedishes", EATING_OUT),
        ("presto", TRANSPORT),
    ]


def seed_rules() -> list[Rule]:
    """The Rules a fresh database starts with."""
    return [Rule("merchant", pattern, bucket) for pattern, bucket in _merchant_rules()] + [
        Rule("plaid_category", pattern, bucket) for pattern, bucket in _plaid_rules()
    ]


SEED_RULES = seed_rules()
