from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api.dependencies import get_request_db
from src.api.query_validation import validate_date, validate_partner


def test_validate_date_rejects_missing_value_with_existing_bad_request():
    with pytest.raises(HTTPException) as exc_info:
        validate_date(None)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Date parameter is required (YYYY-MM-DD format)."


def test_validate_date_rejects_invalid_value_with_existing_bad_request():
    with pytest.raises(HTTPException) as exc_info:
        validate_date("14-08-2026")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == (
        "Invalid date format: '14-08-2026'. Expected YYYY-MM-DD."
    )


def test_validate_partner_rejects_blank_optional_value():
    with pytest.raises(HTTPException) as exc_info:
        validate_partner("   ")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Partner identifier cannot be empty."


def test_validate_partner_trims_required_value():
    assert validate_partner("  MOMO  ", required=True) == "MOMO"


def test_get_request_db_rejects_missing_database_with_existing_service_unavailable():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(HTTPException) as exc_info:
        get_request_db(request)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database connection not available."
