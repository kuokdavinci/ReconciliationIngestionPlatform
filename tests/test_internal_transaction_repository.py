from datetime import datetime
from zoneinfo import ZoneInfo

from src.infrastructure.postgres.internal_transaction_repository import as_utc_naive


def test_business_time_bounds_are_converted_to_utc_before_sql_query():
    value = datetime(2026, 8, 10, 0, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

    assert as_utc_naive(value) == datetime(2026, 8, 9, 17, 0)
