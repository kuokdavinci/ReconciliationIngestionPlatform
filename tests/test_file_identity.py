from hashlib import sha256

from src.core.file_identity import compute_file_hash


def test_compute_file_hash_returns_sha256_for_file_bytes(tmp_path) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"canonical-file-content")

    assert compute_file_hash(str(source)) == sha256(b"canonical-file-content").hexdigest()
