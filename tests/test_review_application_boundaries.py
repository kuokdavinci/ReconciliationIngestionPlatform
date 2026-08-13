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
