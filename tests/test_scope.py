from src.core.enums import ReconciliationScopeType
from src.reconciliation.scope import classify_key_scope


def test_first_delivery_is_full_snapshot_without_history():
    result = classify_key_scope(
        incoming_keys={"a", "b"},
        historical_keys=set(),
        prior_file_count=0,
    )

    assert result["scopeType"] == ReconciliationScopeType.FULL_SNAPSHOT.value


def test_batch_with_only_new_keys_is_append():
    result = classify_key_scope(
        incoming_keys={"c", "d"},
        historical_keys={"a", "b"},
        prior_file_count=1,
    )

    assert result["scopeType"] == ReconciliationScopeType.INCREMENTAL_APPEND.value
    assert result["scopeSignals"]["overlapBusinessKeyCount"] == 0


def test_file_covering_history_and_adding_keys_is_replacement():
    result = classify_key_scope(
        incoming_keys={"a", "b", "c"},
        historical_keys={"a", "b"},
        prior_file_count=1,
    )

    assert result["scopeType"] == ReconciliationScopeType.REPLACEMENT.value
    assert result["scopeSignals"]["historicalCoverage"] == 1.0
    assert result["scopeSignals"]["newBusinessKeyCount"] == 1


def test_ambiguous_partial_overlap_requires_review():
    result = classify_key_scope(
        incoming_keys={"a", "b", "c"},
        historical_keys={"a", "b", "x", "y"},
        prior_file_count=1,
    )

    assert result["scopeType"] == ReconciliationScopeType.UNCONFIRMED.value


def test_blank_keys_are_ignored_and_do_not_trigger_changed_key_logic():
    result = classify_key_scope(
        incoming_keys={"  ", "a"},
        historical_keys={"a"},
        prior_file_count=1,
    )

    assert result["scopeSignals"]["incomingUniqueBusinessKeyCount"] == 1
    assert "changedOverlapKeyCount" not in result["scopeSignals"]
