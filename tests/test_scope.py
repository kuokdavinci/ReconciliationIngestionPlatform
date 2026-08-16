from types import SimpleNamespace

from src.core.enums import ReconciliationScopeType
from src.reconciliation.scope import classify_key_scope
from src.application.review.scope_support import (
    _apply_scope_guardrails,
    _column_index,
    _extract_scope_keys,
    _normalize_scope_probabilities,
    _scope_mapping_columns,
    _scope_probabilities,
)


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


def test_scope_probabilities_choose_incremental_for_a_materially_smaller_file():
    probabilities, scope, reasoning = _scope_probabilities(
        internal_count=100,
        received_count=20,
    )

    assert scope == "INCREMENTAL_APPEND"
    assert probabilities[scope] == 0.72
    assert reasoning


def test_scope_probabilities_normalize_non_negative_values_to_one():
    probabilities = _normalize_scope_probabilities(
        {"FULL_SNAPSHOT": 2, "INCREMENTAL_APPEND": -1, "REPLACEMENT": 1}
    )

    assert probabilities == {
        "FULL_SNAPSHOT": 2 / 3,
        "INCREMENTAL_APPEND": 0.0,
        "REPLACEMENT": 1 / 3,
    }


def test_scope_guardrails_replace_small_gap_incremental_prediction():
    result = _apply_scope_guardrails(
        ai_scope="INCREMENTAL_APPEND",
        ai_probabilities={"FULL_SNAPSHOT": 0.1, "INCREMENTAL_APPEND": 0.8, "REPLACEMENT": 0.1},
        ai_reasoning="AI suggested append.",
        heuristic_scope="FULL_SNAPSHOT",
        heuristic_probabilities={"FULL_SNAPSHOT": 0.8, "INCREMENTAL_APPEND": 0.1, "REPLACEMENT": 0.1},
        heuristic_reasoning="Counts are close.",
        internal_count=10_000,
        received_count=9_600,
    )

    assert result[0] == {"FULL_SNAPSHOT": 0.8, "INCREMENTAL_APPEND": 0.1, "REPLACEMENT": 0.1}
    assert result[1] == "FULL_SNAPSHOT"
    assert result[3] == "guardrail_override_small_gap"


def test_column_index_supports_numeric_and_excel_references():
    assert _column_index(1) == 0
    assert _column_index("B") == 1
    assert _column_index("AA") == 26
    assert _column_index(0) is None


def test_scope_mapping_columns_uses_transaction_key_mapping():
    config = SimpleNamespace(
        field_mappings=[SimpleNamespace(path="transaction.trace", column="B")]
    )

    assert _scope_mapping_columns(config) == {"trace": "B"}


def test_extract_scope_keys_handles_list_and_dict_rows():
    config = SimpleNamespace(
        field_mappings=[SimpleNamespace(path="trace", column=2)]
    )

    list_count, list_keys = _extract_scope_keys(
        [("1", "LIST-1"), ("2", "LIST-2")], config
    )
    dict_count, dict_keys = _extract_scope_keys(
        [{"2": "DICT-1"}, {"B": "DICT-2"}], config
    )

    assert (list_count, list_keys) == (2, {"LIST-1", "LIST-2"})
    assert (dict_count, dict_keys) == (2, {"DICT-1", "DICT-2"})
