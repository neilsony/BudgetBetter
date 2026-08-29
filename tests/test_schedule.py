import datetime as dt

from budgetbetter.schedule import ANCHOR_PAYDAY, is_payday, next_payday


def test_the_anchor_date_is_a_payday():
    assert is_payday(ANCHOR_PAYDAY)


def test_paydays_repeat_every_fourteen_days_after_the_anchor():
    assert is_payday(dt.date(2026, 9, 4))
    assert is_payday(dt.date(2026, 9, 18))
    assert is_payday(dt.date(2026, 10, 2))


def test_paydays_run_backwards_from_the_anchor_too():
    assert is_payday(dt.date(2026, 8, 7))
    assert is_payday(dt.date(2026, 7, 24))


def test_the_off_week_friday_is_not_a_payday():
    assert not is_payday(dt.date(2026, 8, 28))
    assert not is_payday(dt.date(2026, 9, 11))


def test_a_weekday_inside_a_payday_week_is_not_a_payday():
    assert not is_payday(dt.date(2026, 9, 3))
    assert not is_payday(dt.date(2026, 9, 5))


def test_next_payday_skips_todays_payday():
    assert next_payday(dt.date(2026, 9, 4)) == dt.date(2026, 9, 18)


def test_next_payday_from_a_non_payday_finds_the_upcoming_one():
    assert next_payday(dt.date(2026, 8, 28)) == dt.date(2026, 9, 4)
