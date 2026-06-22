"""Tests for Phase 20 features: Reconciliation Insights and Contextual Copilot per Screen."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from src.api.reconciliation import reconciliation_insights
from src.api.copilot import get_context

def _make_request(db: MagicMock):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))

class _AsyncCursor:
    def __init__(self, docs):
        self._docs = docs
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        value = self._docs[self._idx]
        self._idx += 1
        return value

def _make_collection(docs=None):
    collection = MagicMock()
    collection.find = MagicMock(side_effect=lambda *_args, **_kwargs: _AsyncCursor(docs or []))
    collection.find_one = AsyncMock(return_value=None)
    return collection

@pytest.mark.asyncio
async def test_reconciliation_insights_summary():
    db = MagicMock()
    request = _make_request(db)
    
    # Mock get_summary to return a static dictionary
    mock_summary = {
        "partner": "MOMO",
        "date": "2026-06-05",
        "summary_metrics": {"total_transactions": 10},
        "grouped_stats": [],
        "key_findings": []
    }
    
    with (
        patch("src.analysis.insights.get_summary", new_callable=AsyncMock) as mock_get_summary,
        patch("src.api.reconciliation._resolve_latest_run_filters", new_callable=AsyncMock, return_value={}) as mock_filters,
    ):
        mock_get_summary.return_value = mock_summary
        
        result = await reconciliation_insights(
            request=request,
            partner="MOMO",
            date="2026-06-05",
            type="summary"
        )
        
        assert result["partner"] == "MOMO"
        assert "generated_at" in result
        mock_get_summary.assert_called_once()

@pytest.mark.asyncio
async def test_reconciliation_insights_discrepancies():
    db = MagicMock()
    request = _make_request(db)
    
    mock_result_item = MagicMock()
    mock_result_item.model_dump.return_value = {
        "type": "amount_mismatch",
        "severity": "high",
        "title": "Mismatch"
    }
    
    with (
        patch("src.analysis.insights.get_discrepancies", new_callable=AsyncMock) as mock_get_discrepancies,
        patch("src.api.reconciliation._resolve_latest_run_filters", new_callable=AsyncMock, return_value={}) as mock_filters,
    ):
        mock_get_discrepancies.return_value = [mock_result_item]
        
        result = await reconciliation_insights(
            request=request,
            partner="MOMO",
            date="2026-06-05",
            type="anomalies"
        )
        
        assert len(result) == 1
        assert result[0]["type"] == "amount_mismatch"
        from unittest.mock import ANY
        mock_get_discrepancies.assert_called_once_with(
            partner="MOMO",
            date="2026-06-05",
            focus="inconsistency",
            collection=db["reconciliation_result"],
            llm_provider=ANY,
            extra_query={}
        )

@pytest.mark.asyncio
async def test_copilot_context_review_screen():
    db = MagicMock()
    
    # Mock collections to return empty lists to avoid errors
    file_col = _make_collection([])
    mapping_col = _make_collection([])
    packet_col = _make_collection([])
    
    def get_collection(name):
        if name == "reconciliation_file": return file_col
        if name == "reconciliation_mapping_config": return mapping_col
        if name == "review_packet": return packet_col
        return MagicMock()
    db.__getitem__ = MagicMock(side_effect=get_collection)
    
    request = _make_request(db)
    
    result = await get_context(
        request=request,
        partner="MOMO",
        date="2026-06-05",
        screen="review"
    )
    
    assert "Review Center" in result["headline"]
    assert result["status"] == "healthy"  # No pending items

@pytest.mark.asyncio
async def test_copilot_context_reconciliation_screen():
    db = MagicMock()
    
    # Mock reconciliation results
    recon_col = _make_collection([])
    file_col = _make_collection([])
    mapping_col = _make_collection([])
    packet_col = _make_collection([])
    
    def get_collection(name):
        if name == "reconciliation_result": return recon_col
        if name == "reconciliation_file": return file_col
        if name == "reconciliation_mapping_config": return mapping_col
        if name == "review_packet": return packet_col
        return MagicMock()
    db.__getitem__ = MagicMock(side_effect=get_collection)
    
    request = _make_request(db)
    
    with patch("src.models.reconciliation_result.ReconciliationResultRepository.count_by_status", new_callable=AsyncMock) as mock_count:
        mock_count.return_value = {"MATCHED": 10, "AMOUNT_MISMATCH": 2}
        
        result = await get_context(
            request=request,
            partner="MOMO",
            date="2026-06-05",
            screen="reconciliation"
        )
        
        assert "anomalies detected" in result["headline"]
        assert result["status"] == "monitor"
        mock_count.assert_called_once_with("MOMO", "2026-06-05")
