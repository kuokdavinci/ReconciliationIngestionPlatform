from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = ROOT / "src" / "application" / "review"
COPILOT_ROOT = ROOT / "src" / "application" / "copilot"


def test_review_application_has_no_fastapi_or_api_dependency() -> None:
    assert REVIEW_ROOT.exists()
    source = "\n".join(path.read_text() for path in REVIEW_ROOT.glob("*.py"))

    assert "from fastapi" not in source
    assert "src.api" not in source
    assert "HTTPException" not in source
    assert "Request" not in source


def test_copilot_application_has_no_fastapi_or_api_dependency() -> None:
    assert COPILOT_ROOT.exists()
    source = "\n".join(path.read_text() for path in COPILOT_ROOT.glob("*.py"))

    assert "from fastapi" not in source
    assert "src.api" not in source
    assert "HTTPException" not in source
    assert "Request" not in source


def test_review_errors_are_transport_neutral() -> None:
    from src.application.review.errors import (
        ReviewConflictError,
        ReviewNotFoundError,
        ReviewUnavailableError,
        ReviewValidationError,
    )

    for error_type in (
        ReviewNotFoundError,
        ReviewConflictError,
        ReviewValidationError,
        ReviewUnavailableError,
    ):
        assert not hasattr(error_type, "status_code")


def test_config_health_delegates_review_artifact_creation_to_application() -> None:
    source = (ROOT / "src" / "config" / "config_health.py").read_text()

    assert "src.application.review.proposal_creation" in source
    assert "ReviewPacket(" not in source
    assert "CopilotAction(" not in source
    assert "from src.domain.review.models import" not in source
    assert "from src.infrastructure.review.repository import" not in source


def test_reprocessing_is_a_facade_for_replay_and_post_approval_lifecycle() -> None:
    source = (REVIEW_ROOT / "reprocessing.py").read_text()

    assert "staged_page_replay" in source
    assert "post_approval_reconciliation" in source
    assert "RawIngestionPageRepository(db)" not in source
    assert "build_reconciliation_service(db" not in source
    assert "async def reprocess_staged_pages" in source
    assert "async def reprocess_and_reconcile" in source
