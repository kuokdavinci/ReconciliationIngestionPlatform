"""Canonical file identity helpers shared by ingestion adapters."""

import hashlib


def compute_file_hash(file_path: str) -> str:
    """Return a stable SHA-256 fingerprint for a local source file."""

    digest = hashlib.sha256()
    with open(file_path, "rb") as source_file:
        for chunk in iter(lambda: source_file.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()
