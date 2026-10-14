from datetime import datetime, timezone, timedelta

from app.main import compute_late_minutes, compute_work_hours, compute_overtime


IST = timezone(timedelta(hours=5, minutes=30))


def test_late_minutes_within_grace_period():
    punch_in = datetime(2026, 10, 13, 9, 39, 59, tzinfo=IST)
    assert compute_late_minutes(punch_in, "09:30") == 0


def test_late_minutes_at_exactly_ten_minutes():
    punch_in = datetime(2026, 10, 13, 9, 40, 0, tzinfo=IST)
    assert compute_late_minutes(punch_in, "09:30") == 0


def test_late_minutes_after_grace_period():
    punch_in = datetime(2026, 10, 13, 9, 40, 1, tzinfo=IST)
    assert compute_late_minutes(punch_in, "09:30") == 10


def test_late_minutes_at_1015_59():
    punch_in = datetime(2026, 10, 13, 10, 15, 59, tzinfo=IST)
    assert compute_late_minutes(punch_in, "09:30") == 45


def test_work_hours():
    punch_in = datetime(2026, 10, 13, 9, 30, tzinfo=IST)
    punch_out = datetime(2026, 10, 13, 18, 0, tzinfo=IST)
    assert compute_work_hours(punch_in, punch_out) == 8.5


def test_overtime_below_thirty_minutes():
    punch_out = datetime(2026, 10, 13, 18, 59, tzinfo=IST)
    assert compute_overtime(punch_out, "18:30", "2026-10-13") == 0


def test_overtime_at_thirty_minutes():
    punch_out = datetime(2026, 10, 13, 19, 0, tzinfo=IST)
    assert compute_overtime(punch_out, "18:30", "2026-10-13") == 30

def test_late_minutes_before_shift_start():
    punch_in = datetime(2026, 10, 13, 9, 29, 59, tzinfo=IST)
    assert compute_late_minutes(punch_in, "09:30") == 0


def test_late_minutes_one_hour_late():
    punch_in = datetime(2026, 10, 13, 10, 30, 0, tzinfo=IST)
    assert compute_late_minutes(punch_in, "09:30") == 60


def test_work_hours_rounds_to_two_decimals():
    punch_in = datetime(2026, 10, 13, 9, 0, 0, tzinfo=IST)
    punch_out = datetime(2026, 10, 13, 9, 20, 59, tzinfo=IST)
    assert compute_work_hours(punch_in, punch_out) == 0.35


def test_overtime_exactly_twenty_nine_minutes_is_zero():
    punch_out = datetime(2026, 10, 13, 18, 59, 0, tzinfo=IST)
    assert compute_overtime(
        punch_out, "18:30", "2026-10-13"
    ) == 0

def test_overnight_late_minutes_after_midnight():
    punch_in = datetime(2026, 10, 14, 0, 30, 0, tzinfo=IST)

    assert compute_late_minutes(
        punch_in,
        "22:00",
        "06:00",
    ) == 150


def test_overnight_overtime():
    punch_out = datetime(2026, 10, 14, 6, 45, 0, tzinfo=IST)

    assert compute_overtime(
        punch_out,
        "06:00",
        "2026-10-13",
        "22:00",
    ) == 45

def test_work_hours_uses_half_up_rounding():
    punch_in = datetime(2026, 10, 13, 9, 0, 0, tzinfo=IST)
    punch_out = datetime(2026, 10, 13, 10, 7, 30, tzinfo=IST)

    assert compute_work_hours(punch_in, punch_out) == 1.13
