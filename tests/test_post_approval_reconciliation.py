from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.ingestion.contracts import IngestionResult
from src.application.review.post_approval_reconciliation import (
    continue_waiting_post_approval_run,
    reconcile_approved_packet,
)
from src.core.enums import ProcessingStatus
from src.core.types import ProcessingStats
from src.domain.ingestion.quality import QualityDecision, QualitySummary
from src.domain.review.models import PostApprovalQualityGateStatus, PostApprovalRunStatus


@pytest.mark.asyncio
async def test_post_approval_batch_fatal_is_projected_before_generic_failed_return():
    reconciliation_date = datetime(2026, 8, 28, tzinfo=timezone.utc)
    packet = SimpleNamespace(
        id="packet-batch-fatal",
        partner="MOMO",
        reconciliation_date=reconciliation_date,
        source_file_path="/source/momo.csv",
        source_file_id="source-file-1",
        raw_stage_key=None,
    )
    config = SimpleNamespace(
        id="mapping-1",
        partner="MOMO",
        workflow_type="UPC",
        file_type="SETTLEMENT",
        config_version="MOMO-v1",
    )
    source_file = SimpleNamespace(
        id="source-file-1",
        reconciliation_date=reconciliation_date,
        processing_status=ProcessingStatus.COMPLETED,
    )
    failed_file = SimpleNamespace(
        id="failed-file-1",
        processing_status=ProcessingStatus.FAILED,
    )
    ingestion_result = IngestionResult(
        file_record=failed_file,
        stats=ProcessingStats(total_rows=10, success_rows=0, failed_rows=10),
        quality_decision=QualityDecision.FAIL,
        quality_summary=QualitySummary(
            decision=QualityDecision.FAIL,
            outcome_counts={"BATCH_FATAL": 1},
            top_rule_codes=["MISSING_REQUIRED_SOURCE_COLUMN"],
        ),
        errors=[{"errorCode": "MISSING_REQUIRED_SOURCE_COLUMN"}],
    )
    pipeline = SimpleNamespace(process_file=AsyncMock(return_value=ingestion_result))
    file_repository = SimpleNamespace(
        find_one=AsyncMock(return_value=source_file),
        delete_one=AsyncMock(),
    )
    transaction_repository = SimpleNamespace(delete_by_source_file=AsyncMock())
    result_repository = SimpleNamespace(delete_by_partner_and_date=AsyncMock())
    runtime_creator = AsyncMock(return_value=SimpleNamespace(id="runtime-1"))
    updater = AsyncMock()
    runtime_updater = AsyncMock()
    review_collection = MagicMock()
    review_collection.update_one = AsyncMock()
    review_repository = SimpleNamespace(collection=review_collection)

    with patch(
        "src.application.review.post_approval_reconciliation.ReviewPacketRepository",
        return_value=review_repository,
    ):
        result = await reconcile_approved_packet(
            db=MagicMock(),
            packet=packet,
            config=config,
            run_id="post-run-1",
            updater=updater,
            source_resolver=lambda _: Path("/tmp/momo.csv"),
            runtime_creator=runtime_creator,
            runtime_updater=runtime_updater,
            file_repository_factory=lambda _: file_repository,
            transaction_repository_factory=lambda _: transaction_repository,
            result_repository_factory=lambda _: result_repository,
            pipeline_builder=lambda **_: pipeline,
            config_loader_builder=lambda _: object(),
            replacement_rebinder=AsyncMock(),
        )

    expected_summary = {
        "outcome": "BATCH_FATAL",
        "errorCodes": ["MISSING_REQUIRED_SOURCE_COLUMN"],
        "totalRows": 10,
        "failedRows": 10,
        "activeRows": 0,
    }
    assert result["qualityGateStatus"] == "FAIL"
    assert result["qualityGateSummary"] == expected_summary
    review_collection.update_one.assert_awaited_once_with(
        {"_id": "packet-batch-fatal"},
        {
            "$set": {
                "qualityGateStatus": "FAIL",
                "qualityGateSummary": expected_summary,
                "postApprovalRunId": "post-run-1",
            }
        },
    )
    final_update = updater.await_args_list[-1].kwargs
    assert final_update["status"] is PostApprovalRunStatus.FAILED
    assert final_update["quality_gate_status"] is PostApprovalQualityGateStatus.FAIL
    assert final_update["quality_gate_summary"] == expected_summary
    assert final_update["stats"]["qualityGate"] == expected_summary


@pytest.mark.asyncio
async def test_quarantine_continuation_completes_checkpoint_and_persists_runtime_outcome():
    reconciliation_date = datetime(2026, 8, 28, tzinfo=timezone.utc)
    run = SimpleNamespace(
        packet_id="packet-quarantine",
        output_file_id="output-file-1",
        source_file_id="staged-file-1",
        stats={},
    )
    run_repository = MagicMock()
    run_repository.collection.find_one_and_update = AsyncMock(return_value={"_id": "run-1"})
    run_repository._from_mongo = MagicMock(return_value=run)
    packet = SimpleNamespace(
        id="packet-quarantine",
        draft_mapping_id="mapping-1",
        active_runtime_config_id=None,
    )
    packet_repository = MagicMock()
    packet_repository.find_one = AsyncMock(return_value=packet)
    config = SimpleNamespace(
        id="mapping-1",
        partner="DEMO",
        config_version="DEMO-v1",
    )
    config_repository = MagicMock()
    config_repository.find_one = AsyncMock(return_value=config)
    source_file = SimpleNamespace(
        id="output-file-1",
        reconciliation_date=reconciliation_date,
        processing_status=ProcessingStatus.PARTIAL,
        fetch_unit_metadata={
            "sourceFileId": "staged-file-1",
            "sourceUnitKeys": ["demo-unit-1"],
        },
        stage_summary={"currentStage": "FINALIZING"},
    )
    file_repository = MagicMock()
    file_repository.find_one = AsyncMock(return_value=source_file)
    runtime_repository = MagicMock()
    runtime_repository.collection.find_one = AsyncMock(return_value={"_id": "runtime-1"})
    checkpoint = SimpleNamespace(
        current_unit_key=None,
        last_completed_unit_key=None,
        unit_timeline=[SimpleNamespace(unit_key="demo-unit-1", page=1, cursor_before=None, cursor_after=None)],
    )
    checkpoint_repository = MagicMock()
    checkpoint_repository.find_one = AsyncMock(return_value=checkpoint)
    checkpoint_repository.mark_stream_completed_after_review = AsyncMock(return_value=True)
    reconciliation = MagicMock()
    reconciliation.reconcile = AsyncMock(return_value=[object(), object()])

    with (
        patch(
            "src.application.review.post_approval_reconciliation.PostApprovalRunRepository",
            return_value=run_repository,
        ),
        patch(
            "src.application.review.post_approval_reconciliation.ReviewPacketRepository",
            return_value=packet_repository,
        ),
        patch(
            "src.application.review.post_approval_reconciliation.MappingConfigRepository",
            return_value=config_repository,
        ),
        patch(
            "src.application.review.post_approval_reconciliation.IngestionCheckpointRepository",
            return_value=checkpoint_repository,
        ),
        patch(
            "src.application.review.post_approval_reconciliation.update_post_approval_run",
            new=AsyncMock(),
        ),
        patch(
            "src.application.review.post_approval_reconciliation.update_runtime_run",
            new=AsyncMock(),
        ) as runtime_update,
        patch(
            "src.application.review.post_approval_reconciliation._persist_packet_quality_gate",
            new=AsyncMock(),
        ),
        patch(
            "src.application.review.post_approval_reconciliation._quarantine_quality_gate",
            new=AsyncMock(
                return_value=(
                    PostApprovalQualityGateStatus.PASS,
                    {"totalRows": 1, "activeRows": 0},
                )
            ),
        ),
    ):
        result = await continue_waiting_post_approval_run(
            MagicMock(),
            "run-1",
            packet_repository_factory=lambda _: packet_repository,
            config_repository_factory=lambda _: config_repository,
            run_repository_factory=lambda _: run_repository,
            runtime_repository_factory=lambda _: runtime_repository,
            file_repository_factory=lambda _: file_repository,
            reconciliation_service_builder=lambda _: reconciliation,
            cache_invalidator=AsyncMock(),
        )

    assert result["outcome"] == "RECONCILED_AFTER_QUARANTINE"
    checkpoint_query = checkpoint_repository.find_one.await_args.args[0]
    assert {"sourceFileId": "staged-file-1"} in checkpoint_query["$or"]
    checkpoint_repository.mark_stream_completed_after_review.assert_awaited_once_with(
        checkpoint,
        unit_key="demo-unit-1",
        completed_units=[{"unitKey": "demo-unit-1", "page": 1}],
    )
    runtime_kwargs = runtime_update.await_args.kwargs
    assert runtime_kwargs["stats"]["outcome"] == "PARTIAL"
