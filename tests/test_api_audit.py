"""Tests for audit log endpoint query behavior."""

from src.api.audit import _build_audit_query


def test_build_audit_query_filters_by_date_for_date_bound_entities():
    query = _build_audit_query(
        entity_type="RECONCILIATION_RUN",
        entity_id=None,
        partner="VNPAY",
        date="2026-06-17",
        action="COMPLETED",
    )

    assert query == {
        "entityType": "RECONCILIATION_RUN",
        "action": "COMPLETED",
        "metadata.partner": "VNPAY",
        "metadata.date": "2026-06-17",
    }


def test_build_audit_query_skips_date_for_date_less_entity_type():
    query = _build_audit_query(
        entity_type="MAPPING_CONFIG",
        entity_id="cfg-001",
        partner="VNPAY",
        date="2026-06-17",
        action="APPROVED",
    )

    assert query == {
        "entityType": "MAPPING_CONFIG",
        "entityId": "cfg-001",
        "action": "APPROVED",
        "metadata.partner": "VNPAY",
    }


def test_build_audit_query_includes_date_less_entities_in_mixed_view():
    query = _build_audit_query(
        entity_type=None,
        entity_id=None,
        partner="VNPAY",
        date="2026-06-17",
        action=None,
    )

    assert query == {
        "metadata.partner": "VNPAY",
        "$or": [
            {"metadata.date": "2026-06-17"},
            {
                "entityType": {"$in": ["MAPPING_CONFIG"]},
                "metadata.date": {"$exists": False},
            },
        ],
    }
