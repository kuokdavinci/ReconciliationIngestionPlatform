import threading
from hashlib import sha256

import pytest

from src.core.file_identity import compute_file_hash
from src.fetchers.base import BaseFetcher
from src.pipeline import file_claim as file_claim_module
from src.pipeline.file_claim import FileClaimService



def test_compute_file_hash_returns_sha256_for_file_bytes(tmp_path) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"canonical-file-content")

    assert compute_file_hash(str(source)) == sha256(b"canonical-file-content").hexdigest()


def test_base_fetcher_compute_file_hash_delegates_to_canonical_helper(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"canonical-file-content")
    calls = []

    def canonical_helper(file_path: str) -> str:
        calls.append(file_path)
        return "canonical-hash"

    monkeypatch.setattr("src.fetchers.base.compute_file_hash", canonical_helper)

    assert BaseFetcher.compute_file_hash(str(source)) == "canonical-hash"
    assert calls == [str(source)]


@pytest.mark.asyncio
async def test_file_claim_hashing_delegates_to_canonical_helper_in_worker_thread(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"canonical-file-content")
    main_thread = threading.current_thread()
    worker_threads = []

    def canonical_helper(file_path: str) -> str:
        worker_threads.append(threading.current_thread())
        return compute_file_hash(file_path)

    monkeypatch.setattr(file_claim_module, "compute_file_hash", canonical_helper)

    result = await FileClaimService(None, None).compute_file_hash(str(source))

    assert result == sha256(b"canonical-file-content").hexdigest()
    assert worker_threads
    assert worker_threads[0] is not main_thread
