from datetime import date


def test_default_vnpay_backfill_range_contains_four_business_days():
    from scripts.demo.sprint2.seed_vnpay_filedrop_backfill import (
        build_backfill_dates,
        default_backfill_range,
    )

    from_date, to_date = default_backfill_range(date(2026, 8, 17))

    dates = build_backfill_dates(from_date, to_date)
    business_dates = [value for value in dates if value.weekday() < 5]

    assert (from_date, to_date) == ("2026-08-12", "2026-08-17")
    assert business_dates == [
        date(2026, 8, 12),
        date(2026, 8, 13),
        date(2026, 8, 14),
        date(2026, 8, 17),
    ]
