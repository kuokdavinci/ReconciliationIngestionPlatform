from types import SimpleNamespace

from src.api.automation import _AIRFLOW_RETRYING_TASK_STATES, _has_pending_file
from src.domain.fetch_config.models import FetchMethod


def test_completed_api_stream_is_not_reported_as_pending_file():
    latest_file = {
        "id": "api-page-3",
        "processingStatus": "COMPLETED",
    }
    latest_run = SimpleNamespace(
        source_file_id=None,
        status="COMPLETED",
    )

    assert _has_pending_file(
        fetch_method=FetchMethod.API,
        latest_file=latest_file,
        latest_run=latest_run,
        is_duplicate_outcome=False,
    ) is False


def test_completed_file_route_can_still_report_an_unconsumed_file():
    latest_file = {
        "id": "file-1",
        "processingStatus": "COMPLETED",
    }
    latest_run = SimpleNamespace(
        source_file_id=None,
        status="COMPLETED",
    )

    assert _has_pending_file(
        fetch_method=FetchMethod.FILEDROP,
        latest_file=latest_file,
        latest_run=latest_run,
        is_duplicate_outcome=False,
    ) is True


def test_airflow_running_states_are_not_misreported_as_retrying():
    assert _AIRFLOW_RETRYING_TASK_STATES == {"up_for_retry"}
