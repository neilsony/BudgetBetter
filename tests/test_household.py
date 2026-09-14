"""The shared ledger: the maths first, then the pages.

The split and Balance arithmetic gets thorough unit coverage because that is
where a wrong answer costs somebody real money. The pages get shallow smoke
tests in the house style — except the authorisation ones, which are the point
of ADR-0014 and are checked properly.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from budgetbetter.app import app, get_connection
from budgetbetter.config import get_settings
from budgetbetter.core import db
from budgetbetter.crypto import generate_key
from budgetbetter.household import auth
from budgetbetter.household import db as household_db
from budgetbetter.household import disputes as disputes_mod
from budgetbetter.household import ledger
from budgetbetter.household.models import money

from conftest import sign_in


# --- Splitting -------------------------------------------------------------


def test_an_equal_split_of_an_indivisible_total_loses_no_pennies():
    amounts = ledger.allocate_equally(10000, [1, 2, 3], payer_id=1)
    assert sum(amounts.values()) == 10000
    assert sorted(amounts.values()) == [3333, 3333, 3334]


def test_the_odd_penny_goes_to_the_payer_first():
    """They are the one out of pocket, so they carry the rounding."""
    amounts = ledger.allocate_equally(10000, [7, 8, 9], payer_id=9)
    assert amounts[9] == 3334


def test_leftover_pennies_after_the_payer_go_in_stable_member_order():
    amounts = ledger.allocate_equally(1000, [1, 2, 3], payer_id=3)
    assert amounts == {3: 334, 1: 333, 2: 333}


def test_every_split_mode_adds_back_to_the_total():
    for mode, kwargs in [
        ("equal_all", {"member_ids": [1, 2, 3]}),
        ("equal_selected", {"member_ids": [2, 3]}),
        ("reimbursement", {"member_ids": [2, 3]}),
        ("custom", {"member_ids": [], "custom_cents": {1: 1, 2: 6000, 3: 3999}}),
    ]:
        amounts = ledger.shares_for(mode, total_cents=10000, payer_id=1, **kwargs)
        assert sum(amounts.values()) == 10000, mode


def test_an_equal_split_always_includes_the_payer():
    """The total is what they are seeking reimbursement for; their portion is theirs."""
    amounts = ledger.shares_for("equal_selected", total_cents=900, member_ids=[2], payer_id=1)
    assert set(amounts) == {1, 2}


def test_a_full_reimbursement_leaves_the_payer_with_no_share():
    amounts = ledger.shares_for("reimbursement", total_cents=4500, member_ids=[2], payer_id=1)
    assert amounts == {2: 4500}


def test_a_custom_split_that_does_not_add_up_is_refused():
    with pytest.raises(ledger.SplitError):
        ledger.shares_for(
            "custom", total_cents=10000, member_ids=[], payer_id=1, custom_cents={2: 4000}
        )


def test_a_custom_split_may_give_the_payer_nothing():
    """Buying something entirely for someone else, without the reimbursement mode."""
    amounts = ledger.shares_for(
        "custom", total_cents=4500, member_ids=[], payer_id=1, custom_cents={1: 0, 2: 4500}
    )
    assert amounts == {2: 4500}


def test_money_formats_cents_without_floating_point_drift():
    assert money(115_82) == "$115.82"
    assert money(-1025_00) == "-$1,025.00"


# --- Balances --------------------------------------------------------------


def _line(member_id, payer_id, cents, status="owed", expense_id=1, void=False):
    from budgetbetter.household.models import Expense, Share

    share = Share(
        id=member_id * 100 + expense_id,
        expense_id=expense_id,
        member_id=member_id,
        amount_cents=cents,
        status=status,
    )
    expense = Expense(
        id=expense_id,
        payer_id=payer_id,
        created_by=payer_id,
        description="Something",
        total_cents=cents,
        kind="general",
        split_mode="custom",
        incurred_on=dt.date(2026, 9, 1),
        created_at="2026-09-01T00:00:00",
        voided_at="2026-09-02T00:00:00" if void else None,
    )
    return share, expense


def test_opposing_debts_between_the_same_pair_cancel():
    lines = [_line(1, 2, 10000, expense_id=1), _line(2, 1, 6000, expense_id=2)]
    assert ledger.net_by_member(lines, me_id=1) == {2: 4000}


def test_a_claimed_share_still_counts_until_the_payer_confirms():
    lines = [_line(1, 2, 10000, status="claimed")]
    assert ledger.net_by_member(lines, me_id=1) == {2: 10000}


def test_a_paid_share_counts_for_nobody():
    lines = [_line(1, 2, 10000, status="paid")]
    assert ledger.net_by_member(lines, me_id=1) == {}


def test_a_disputed_share_leaves_both_sides_totals():
    """Neither dashboard quietly absorbs a contested amount."""
    lines = [_line(1, 2, 10000, status="disputed")]
    assert ledger.net_by_member(lines, me_id=1) == {}
    assert ledger.net_by_member(lines, me_id=2) == {}


def test_a_voided_expense_drops_out_of_every_balance():
    lines = [_line(1, 2, 10000, void=True)]
    assert ledger.net_by_member(lines, me_id=1) == {}


def test_totals_report_owing_and_being_owed_separately():
    from budgetbetter.household.models import Balance, Member

    def member(i):
        return Member(i, f"M{i}", f"m{i}@x.com", "member", dt.date(2026, 1, 1))

    owe, owed = ledger.totals(
        [Balance(member(2), 4000), Balance(member(3), -2500)]
    )
    assert (owe, owed) == (4000, 2500)


# --- Disputes --------------------------------------------------------------


@pytest.fixture
def house(conn, owner, make_member):
    """The Owner plus five roommates, which is the real shape of this house."""
    others = [
        make_member(name, f"{name.lower()}@house.test")
        for name in ("Rowan", "Zak", "Mason", "Jonathan", "Oliver")
    ]
    return {"owner": owner, "others": others, "all": [owner, *others]}


def _utilities(conn, house, total=60000):
    """$600 of utilities, six ways at $100, paid by the Owner."""
    ids = [m.id for m in house["all"]]
    amounts = ledger.allocate_equally(total, ids, payer_id=house["owner"].id)
    with db.writing(conn):
        expense_id = household_db.create_expense(
            conn,
            payer_id=house["owner"].id,
            created_by=house["owner"].id,
            description="Utilities",
            total_cents=total,
            kind="general",
            split_mode="equal_all",
            incurred_on=dt.date(2026, 9, 1),
            share_amounts=amounts,
        )
    return household_db.get_expense(conn, expense_id)


def _dispute(conn, expense, member_id, reason="I was away all month"):
    share = next(s for s in expense.shares if s.member_id == member_id)
    with db.writing(conn):
        household_db.set_share_status(conn, share.id, "disputed")
        dispute_id = household_db.raise_dispute(
            conn, share_id=share.id, raised_by=member_id, reason=reason
        )
    return dispute_id, share


def test_upholding_a_dispute_redistributes_to_everyone_else_including_the_payer(conn, house):
    """The worked example from ADR-0017, end to end."""
    expense = _utilities(conn, house)
    oliver = house["others"][-1]
    dispute_id, share = _dispute(conn, expense, oliver.id)

    with db.writing(conn):
        result = disputes_mod.resolve(
            conn, dispute_id, outcome="upheld", resolver_id=house["owner"].id
        )

    assert result.redistributed_cents == 10000
    resolution = household_db.get_expense(conn, result.resolution_expense_id)

    # Five people carry it — everyone on the expense except the disputer, and
    # the payer is one of them.
    assert len(resolution.shares) == 5
    assert sum(s.amount_cents for s in resolution.shares) == 10000
    assert all(s.amount_cents == 2000 for s in resolution.shares)
    assert house["owner"].id in {s.member_id for s in resolution.shares}
    assert oliver.id not in {s.member_id for s in resolution.shares}


def test_the_payers_own_slice_of_a_redistribution_is_absorbed_not_owed(conn, house):
    expense = _utilities(conn, house)
    oliver = house["others"][-1]
    dispute_id, _ = _dispute(conn, expense, oliver.id)
    with db.writing(conn):
        result = disputes_mod.resolve(
            conn, dispute_id, outcome="upheld", resolver_id=house["owner"].id
        )

    resolution = household_db.get_expense(conn, result.resolution_expense_id)
    payer_share = next(s for s in resolution.shares if s.member_id == house["owner"].id)
    assert payer_share.status == "paid"

    # The Owner paid $600 and now recovers $480: they absorbed $20 of the $100.
    lines = household_db.all_lines(conn)
    net = ledger.net_by_member(lines, me_id=house["owner"].id)
    assert sum(-v for v in net.values() if v < 0) == 48000


def test_the_disputer_owes_nothing_and_the_others_owe_more(conn, house):
    expense = _utilities(conn, house)
    oliver, rowan = house["others"][-1], house["others"][0]
    dispute_id, _ = _dispute(conn, expense, oliver.id)
    with db.writing(conn):
        disputes_mod.resolve(conn, dispute_id, outcome="upheld", resolver_id=house["owner"].id)

    lines = household_db.all_lines(conn)
    assert ledger.net_by_member(lines, me_id=oliver.id) == {}
    assert ledger.net_by_member(lines, me_id=rowan.id) == {house["owner"].id: 12000}


def test_amending_redistributes_only_the_difference(conn, house):
    expense = _utilities(conn, house)
    oliver = house["others"][-1]
    dispute_id, share = _dispute(conn, expense, oliver.id)

    with db.writing(conn):
        result = disputes_mod.resolve(
            conn,
            dispute_id,
            outcome="amended",
            resolver_id=house["owner"].id,
            amended_cents=4000,
        )

    assert result.redistributed_cents == 6000
    assert household_db.get_share(conn, share.id).amount_cents == 4000
    assert household_db.get_share(conn, share.id).status == "owed"
    resolution = household_db.get_expense(conn, result.resolution_expense_id)
    assert sum(s.amount_cents for s in resolution.shares) == 6000


def test_denying_a_dispute_restores_the_share_untouched(conn, house):
    expense = _utilities(conn, house)
    oliver = house["others"][-1]
    dispute_id, share = _dispute(conn, expense, oliver.id)

    with db.writing(conn):
        result = disputes_mod.resolve(
            conn, dispute_id, outcome="denied", resolver_id=house["owner"].id
        )

    assert result.resolution_expense_id is None
    restored = household_db.get_share(conn, share.id)
    assert restored.status == "owed"
    assert restored.amount_cents == 10000


def test_an_amendment_cannot_raise_a_share(conn, house):
    expense = _utilities(conn, house)
    dispute_id, _ = _dispute(conn, expense, house["others"][-1].id)
    with pytest.raises(disputes_mod.DisputeError):
        with db.writing(conn):
            disputes_mod.resolve(
                conn,
                dispute_id,
                outcome="amended",
                resolver_id=house["owner"].id,
                amended_cents=50000,
            )


def test_a_dispute_resolution_expense_cannot_itself_be_disputed(conn, house):
    """Otherwise the chain has no natural end."""
    expense = _utilities(conn, house)
    dispute_id, _ = _dispute(conn, expense, house["others"][-1].id)
    with db.writing(conn):
        result = disputes_mod.resolve(
            conn, dispute_id, outcome="upheld", resolver_id=house["owner"].id
        )
    resolution = household_db.get_expense(conn, result.resolution_expense_id)
    assert not resolution.disputable


def test_a_dispute_cannot_be_resolved_twice(conn, house):
    expense = _utilities(conn, house)
    dispute_id, _ = _dispute(conn, expense, house["others"][-1].id)
    with db.writing(conn):
        disputes_mod.resolve(conn, dispute_id, outcome="denied", resolver_id=house["owner"].id)
    with pytest.raises(disputes_mod.DisputeError):
        with db.writing(conn):
            disputes_mod.resolve(conn, dispute_id, outcome="upheld", resolver_id=house["owner"].id)


# --- Locking ---------------------------------------------------------------


def test_an_expense_with_a_paid_share_is_locked(conn, house):
    expense = _utilities(conn, house)
    assert not expense.locked
    share = next(s for s in expense.shares if s.member_id == house["others"][0].id)
    with db.writing(conn):
        household_db.set_share_status(conn, share.id, "paid", paid_by=house["owner"].id)
    assert household_db.get_expense(conn, expense.id).locked


def test_an_expense_with_a_disputed_share_is_locked(conn, house):
    expense = _utilities(conn, house)
    _dispute(conn, expense, house["others"][0].id)
    assert household_db.get_expense(conn, expense.id).locked


def test_editing_an_unlocked_expense_resplits_it(conn, house, owner_client):
    expense = _utilities(conn, house)
    response = owner_client.post(
        f"/household/expenses/{expense.id}/edit",
        data={
            "csrf": auth.csrf_for_session(owner_client.cookies.get(auth.SESSION_COOKIE)),
            "description": "Hydro (corrected)",
            "amount": "660.00",
            "incurred_on": "2026-09-02",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    edited = household_db.get_expense(conn, expense.id)
    assert edited.description == "Hydro (corrected)"
    assert edited.total_cents == 66000
    assert sum(s.amount_cents for s in edited.shares) == 66000
    assert all(s.amount_cents == 11000 for s in edited.shares)


def test_a_locked_expense_cannot_be_edited(conn, house, owner_client):
    expense = _utilities(conn, house)
    _dispute(conn, expense, house["others"][0].id)
    response = owner_client.post(
        f"/household/expenses/{expense.id}/edit",
        data={
            "csrf": auth.csrf_for_session(owner_client.cookies.get(auth.SESSION_COOKIE)),
            "description": "Nope",
            "amount": "1.00",
        },
        follow_redirects=False,
    )
    assert "no+longer+be+edited" in response.headers["location"]
    assert household_db.get_expense(conn, expense.id).total_cents == 60000


def test_the_payers_own_share_starts_paid(conn, house):
    expense = _utilities(conn, house)
    own = next(s for s in expense.shares if s.member_id == house["owner"].id)
    assert own.status == "paid"


# --- Rent ------------------------------------------------------------------


def test_rent_shares_come_from_the_table_verbatim(conn, house):
    """Unequal, fixed, and nothing typed in — which is the whole point."""
    figures = dict(zip([m.id for m in house["all"]], [102500, 90000, 90000, 90000, 90000, 97500]))
    with db.writing(conn):
        for member_id, cents in figures.items():
            household_db.set_rent_share(conn, member_id, cents)

    stored = household_db.rent_shares(conn)
    assert stored == figures
    assert sum(stored.values()) == 560000


def test_rent_for_the_month_is_found_so_a_second_press_can_warn(conn, house):
    with db.writing(conn):
        household_db.create_expense(
            conn,
            payer_id=house["owner"].id,
            created_by=house["owner"].id,
            description="Rent — September 2026",
            total_cents=560000,
            kind="rent",
            split_mode="rent",
            incurred_on=dt.date(2026, 9, 1),
            share_amounts={house["owner"].id: 560000},
        )
    assert household_db.rent_expense_for_month(conn, 2026, 9) is not None
    assert household_db.rent_expense_for_month(conn, 2026, 10) is None


def test_a_rent_expense_cannot_be_disputed(conn, house):
    with db.writing(conn):
        expense_id = household_db.create_expense(
            conn,
            payer_id=house["owner"].id,
            created_by=house["owner"].id,
            description="Rent — September 2026",
            total_cents=180000,
            kind="rent",
            split_mode="rent",
            incurred_on=dt.date(2026, 9, 1),
            share_amounts={house["owner"].id: 90000, house["others"][0].id: 90000},
        )
    assert not household_db.get_expense(conn, expense_id).disputable


# --- Departure -------------------------------------------------------------


def test_a_departed_member_leaves_the_split_picker_but_keeps_their_history(conn, house):
    expense = _utilities(conn, house)
    leaving = house["others"][0]
    with db.writing(conn):
        household_db.set_left_on(conn, leaving.id, dt.date(2026, 9, 30))

    active = household_db.list_members(conn, active_only=True)
    assert leaving.id not in {m.id for m in active}
    # But they are still named on the debt they have not settled.
    still_owed = household_db.get_expense(conn, expense.id)
    assert leaving.id in {s.member_id for s in still_owed.shares}
    assert leaving.id in household_db.members_by_id(conn)


def test_writing_off_a_share_clears_it_from_the_balance(conn, house):
    expense = _utilities(conn, house)
    leaver = house["others"][0]
    share = next(s for s in expense.shares if s.member_id == leaver.id)

    before = ledger.net_by_member(household_db.all_lines(conn), me_id=house["owner"].id)
    assert before[leaver.id] == -10000

    with db.writing(conn):
        household_db.write_off_share(
            conn, share_id=share.id, by_member_id=house["owner"].id, reason="Moved out"
        )

    after = ledger.net_by_member(household_db.all_lines(conn), me_id=house["owner"].id)
    assert leaver.id not in after


# --- The pages -------------------------------------------------------------


@pytest.fixture
def owner_client(conn, owner, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", generate_key())
    get_settings.cache_clear()
    app.dependency_overrides[get_connection] = lambda: conn
    yield TestClient(app, cookies=sign_in(conn, owner))
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def member_client(conn, owner, roommate, monkeypatch):
    """Signed in as an ordinary Member — not the Owner."""
    monkeypatch.setenv("APP_ENCRYPTION_KEY", generate_key())
    get_settings.cache_clear()
    app.dependency_overrides[get_connection] = lambda: conn
    yield TestClient(app, cookies=sign_in(conn, roommate))
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_the_household_dashboard_renders(owner_client):
    response = owner_client.get("/household")
    assert response.status_code == 200
    assert "You owe" in response.text


def test_a_member_cannot_reach_the_budgeting_dashboard(member_client):
    """The banking sections are built on the Owner's bank logins. See ADR-0014."""
    assert member_client.get("/", follow_redirects=False).status_code == 403


def test_a_member_cannot_reach_the_investments_page(member_client):
    assert member_client.get("/investments", follow_redirects=False).status_code == 403


def test_a_member_cannot_reach_the_connect_page(member_client):
    assert member_client.get("/connect", follow_redirects=False).status_code == 403


def test_a_member_cannot_trigger_a_refresh(member_client):
    assert member_client.post("/refresh", follow_redirects=False).status_code == 403


def test_a_member_cannot_reach_the_owners_dispute_desk(member_client):
    assert member_client.get("/household/disputes", follow_redirects=False).status_code == 403


def test_a_member_cannot_reach_the_admin_page(member_client):
    assert member_client.get("/household/admin", follow_redirects=False).status_code == 403


def test_the_sidebar_hides_the_banking_links_from_a_member(member_client):
    body = member_client.get("/household").text
    assert "/household" in body
    assert 'href="/investments"' not in body


def test_the_sidebar_shows_the_banking_links_to_the_owner(owner_client):
    body = owner_client.get("/household").text
    assert 'href="/investments"' in body


def test_signing_out_clears_the_session(owner_client, conn):
    token = owner_client.cookies.get(auth.SESSION_COOKIE)
    owner_client.post("/household/logout", follow_redirects=False)
    assert household_db.member_for_session(conn, token) is None


def test_a_stale_form_token_is_refused(owner_client, conn, house):
    expense = _utilities(conn, house)
    share = next(s for s in expense.shares if s.member_id != house["owner"].id)
    response = owner_client.post(
        f"/household/shares/{share.id}/paid", data={"csrf": "not-the-token"}
    )
    assert response.status_code == 400


def test_a_member_cannot_claim_someone_elses_share(member_client, conn, house):
    expense = _utilities(conn, house)
    someone_else = next(s for s in expense.shares if s.member_id == house["others"][0].id)
    token = member_client.cookies.get(auth.SESSION_COOKIE)
    response = member_client.post(
        f"/household/shares/{someone_else.id}/claim",
        data={"csrf": auth.csrf_for_session(token)},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_only_the_person_owed_can_mark_a_share_paid(member_client, conn, house):
    expense = _utilities(conn, house)
    other = next(s for s in expense.shares if s.member_id == house["others"][0].id)
    token = member_client.cookies.get(auth.SESSION_COOKIE)
    response = member_client.post(
        f"/household/shares/{other.id}/paid",
        data={"csrf": auth.csrf_for_session(token)},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_the_first_account_to_register_becomes_the_owner(conn, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("HOUSEHOLD_PIN", "1234")
    get_settings.cache_clear()
    app.dependency_overrides[get_connection] = lambda: conn
    client = TestClient(app)

    client.post(
        "/household/register",
        data={"name": "Neil", "email": "neil@example.com", "password": "longenough1"},
        follow_redirects=False,
    )
    client.post(
        "/household/register",
        data={
            "name": "Zak",
            "email": "zak@example.com",
            "password": "longenough1",
            "pin": "1234",
        },
        follow_redirects=False,
    )

    members = {m.email: m for m in household_db.list_members(conn)}
    assert members["neil@example.com"].role == "owner"
    assert members["zak@example.com"].role == "member"

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_registering_with_the_wrong_house_pin_is_refused(conn, owner, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", generate_key())
    get_settings.cache_clear()
    with db.writing(conn):
        household_db.set_pin_hash(conn, auth.hash_secret("1234"))
    app.dependency_overrides[get_connection] = lambda: conn
    client = TestClient(app)

    client.post(
        "/household/register",
        data={
            "name": "Stranger",
            "email": "stranger@example.com",
            "password": "longenough1",
            "pin": "9999",
        },
        follow_redirects=False,
    )
    assert household_db.get_member_by_email(conn, "stranger@example.com") is None

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# --- Audit -----------------------------------------------------------------


def test_every_change_lands_in_the_audit_trail_with_both_sides(conn, house):
    expense = _utilities(conn, house)
    share = next(s for s in expense.shares if s.member_id == house["others"][0].id)
    with db.writing(conn):
        household_db.record_event(
            conn,
            actor_id=house["owner"].id,
            entity="share",
            entity_id=share.id,
            action="marked_paid",
            before={"status": "owed"},
            after={"status": "paid"},
        )
    events = household_db.events_for(conn, "share", share.id)
    assert events[-1]["before_json"] == '{"status": "owed"}'
    assert events[-1]["after_json"] == '{"status": "paid"}'
    assert events[-1]["actor_id"] == house["owner"].id


# --- The prerequisites from ADR-0018 ---------------------------------------


def test_foreign_keys_are_actually_enforced(conn):
    """Off by default in SQLite, which would make every cascade decorative."""
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_a_write_transaction_takes_the_lock_up_front(conn):
    """`writing` must open IMMEDIATE, not the deferred default."""
    with db.writing(conn):
        assert conn.in_transaction
    assert not conn.in_transaction


def test_a_failed_write_rolls_back(conn, owner):
    with pytest.raises(ValueError):
        with db.writing(conn):
            household_db.create_member(
                conn, name="Ghost", email="ghost@example.com", password_hash="x"
            )
            raise ValueError("something went wrong halfway")
    assert household_db.get_member_by_email(conn, "ghost@example.com") is None
