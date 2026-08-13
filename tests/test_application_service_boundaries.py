import inspect

import src.application.automation.backfill_service as backfill_service
import src.application.runtime.service as runtime_service
import src.domain.ingestion.retry_policy as retry_policy


def test_moved_services_do_not_depend_on_fastapi_or_api_modules() -> None:
    source = "\n".join(
        inspect.getsource(module)
        for module in (backfill_service, runtime_service, retry_policy)
    )

    assert "fastapi" not in source
    assert "src.api" not in source


def test_backfill_errors_do_not_carry_http_transport_metadata() -> None:
    for error_type in (
        backfill_service.BackfillRunValidationError,
        backfill_service.BackfillRunNotFoundError,
        backfill_service.BackfillRunConflictError,
        backfill_service.BackfillRunUnavailableError,
    ):
        assert not hasattr(error_type, "status_code")
