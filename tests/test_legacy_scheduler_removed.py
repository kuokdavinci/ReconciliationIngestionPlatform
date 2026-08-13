from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_scheduler_namespace_and_command_are_removed() -> None:
    assert not (ROOT / "src" / "scheduler").exists()
    assert not (ROOT / "Dockerfile").exists()
    assert "--start-" + "scheduler" not in (ROOT / "run.py").read_text()


def test_viettelpay_mock_uses_dedicated_image() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())

    assert compose["services"]["viettelpay-mock"]["build"]["dockerfile"] == (
        "Dockerfile.viettelpay-mock"
    )
