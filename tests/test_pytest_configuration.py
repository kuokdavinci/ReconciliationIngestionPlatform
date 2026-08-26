from types import SimpleNamespace
from unittest.mock import MagicMock

from tests import conftest


def _config(*, integration: bool = False, e2e: bool = False):
    def getoption(name: str):
        if name == "--integration":
            return integration
        if name == "--e2e":
            return e2e
        raise AssertionError(f"Unexpected pytest option: {name}")

    return SimpleNamespace(getoption=getoption)


def test_integration_tests_are_skipped_by_default():
    item = MagicMock()
    item.keywords = {"integration": True}

    conftest.pytest_collection_modifyitems(_config(), [item])

    item.add_marker.assert_called_once()
    marker = item.add_marker.call_args.args[0]
    assert marker.mark.name == "skip"


def test_integration_flag_keeps_integration_tests_enabled():
    item = MagicMock()
    item.keywords = {"integration": True}

    conftest.pytest_collection_modifyitems(_config(integration=True), [item])

    item.add_marker.assert_not_called()
