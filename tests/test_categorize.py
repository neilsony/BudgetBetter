import datetime as dt

from budgetbetter.buckets import OTHER, SEED_RULES
from budgetbetter.categorize import Rule, is_internal_transfer, resolve_bucket
from budgetbetter.models import Transaction


def txn(
    *,
    merchant_name="Some Shop",
    plaid_primary="GENERAL_MERCHANDISE",
    plaid_detailed="GENERAL_MERCHANDISE_OTHER",
    override_bucket=None,
    amount=10.0,
):
    return Transaction(
        transaction_id="t1",
        account_id="a1",
        date=dt.date(2026, 8, 20),
        name=merchant_name,
        merchant_name=merchant_name,
        amount=amount,
        pending=False,
        plaid_primary=plaid_primary,
        plaid_detailed=plaid_detailed,
        bucket=OTHER,
        override_bucket=override_bucket,
    )


class TestPrecedence:
    def test_an_override_beats_every_rule(self):
        rules = [Rule("merchant", "loblaws", "groceries")]
        assert resolve_bucket(txn(merchant_name="Loblaws", override_bucket="clothes"), rules) == "clothes"

    def test_a_merchant_rule_beats_a_plaid_category_rule(self):
        rules = [
            Rule("merchant", "the beer store", "drinking"),
            Rule("plaid_category", "FOOD_AND_DRINK_GROCERIES", "groceries"),
        ]
        got = resolve_bucket(
            txn(merchant_name="The Beer Store", plaid_detailed="FOOD_AND_DRINK_GROCERIES"), rules
        )
        assert got == "drinking"

    def test_a_detailed_plaid_rule_beats_a_primary_one(self):
        rules = [
            Rule("plaid_category", "FOOD_AND_DRINK", "eating_out"),
            Rule("plaid_category", "FOOD_AND_DRINK_GROCERIES", "groceries"),
        ]
        got = resolve_bucket(
            txn(plaid_primary="FOOD_AND_DRINK", plaid_detailed="FOOD_AND_DRINK_GROCERIES"), rules
        )
        assert got == "groceries"

    def test_an_unmatched_transaction_falls_to_other(self):
        assert resolve_bucket(txn(), []) == OTHER


class TestMerchantMatching:
    def test_merchant_matching_ignores_case(self):
        rules = [Rule("merchant", "STARBUCKS", "eating_out")]
        assert resolve_bucket(txn(merchant_name="starbucks #4471"), rules) == "eating_out"

    def test_merchant_matching_is_a_substring_match(self):
        rules = [Rule("merchant", "uber", "transport")]
        assert resolve_bucket(txn(merchant_name="UBER *TRIP HELP.UBER.COM"), rules) == "transport"

    def test_a_transaction_with_no_merchant_name_still_uses_its_plaid_category(self):
        rules = [Rule("plaid_category", "RENT_AND_UTILITIES_RENT", "rent")]
        got = resolve_bucket(
            txn(merchant_name=None, plaid_detailed="RENT_AND_UTILITIES_RENT"), rules
        )
        assert got == "rent"


class TestSeedRules:
    def test_groceries_land_in_groceries(self):
        got = resolve_bucket(
            txn(plaid_primary="FOOD_AND_DRINK", plaid_detailed="FOOD_AND_DRINK_GROCERIES"),
            SEED_RULES,
        )
        assert got == "groceries"

    def test_restaurants_land_in_eating_out(self):
        got = resolve_bucket(
            txn(plaid_primary="FOOD_AND_DRINK", plaid_detailed="FOOD_AND_DRINK_RESTAURANT"),
            SEED_RULES,
        )
        assert got == "eating_out"

    def test_liquor_lands_in_drinking_not_groceries(self):
        got = resolve_bucket(
            txn(
                plaid_primary="FOOD_AND_DRINK",
                plaid_detailed="FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR",
            ),
            SEED_RULES,
        )
        assert got == "drinking"

    def test_rent_lands_in_rent_while_hydro_lands_in_utilities(self):
        rent = txn(plaid_primary="RENT_AND_UTILITIES", plaid_detailed="RENT_AND_UTILITIES_RENT")
        hydro = txn(
            plaid_primary="RENT_AND_UTILITIES",
            plaid_detailed="RENT_AND_UTILITIES_GAS_AND_ELECTRICITY",
        )
        assert resolve_bucket(rent, SEED_RULES) == "rent"
        assert resolve_bucket(hydro, SEED_RULES) == "utilities"

    def test_a_paycheque_lands_in_income(self):
        got = resolve_bucket(
            txn(plaid_primary="INCOME", plaid_detailed="INCOME_WAGES", amount=-2400.0), SEED_RULES
        )
        assert got == "income"

    def test_a_credit_card_payment_lands_in_transfers(self):
        got = resolve_bucket(
            txn(
                merchant_name="RBC MASTERCARD PAYMENT",
                plaid_primary="LOAN_PAYMENTS",
                plaid_detailed="LOAN_PAYMENTS_CREDIT_CARD_PAYMENT",
            ),
            SEED_RULES,
        )
        assert got == "transfers"


class TestInternalTransferDetection:
    def test_a_credit_card_payment_is_an_internal_transfer(self):
        assert is_internal_transfer(
            txn(plaid_primary="LOAN_PAYMENTS", plaid_detailed="LOAN_PAYMENTS_CREDIT_CARD_PAYMENT")
        )

    def test_money_moving_between_own_accounts_is_an_internal_transfer(self):
        assert is_internal_transfer(
            txn(plaid_primary="TRANSFER_OUT", plaid_detailed="TRANSFER_OUT_ACCOUNT_TRANSFER")
        )
        assert is_internal_transfer(
            txn(plaid_primary="TRANSFER_IN", plaid_detailed="TRANSFER_IN_ACCOUNT_TRANSFER")
        )

    def test_buying_groceries_is_not_an_internal_transfer(self):
        assert not is_internal_transfer(
            txn(plaid_primary="FOOD_AND_DRINK", plaid_detailed="FOOD_AND_DRINK_GROCERIES")
        )

    def test_a_paycheque_is_not_an_internal_transfer(self):
        assert not is_internal_transfer(
            txn(plaid_primary="INCOME", plaid_detailed="INCOME_WAGES", amount=-2400.0)
        )
