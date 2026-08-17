"""Visibility rules for deduplicating review packets in read models."""

from typing import Any


def _identity(packet: Any, attribute: str) -> str | None:
    value = getattr(packet, attribute, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def same_review_source_scope(pending_packet: Any, approved_packet: Any) -> bool:
    """Return whether two same-shaped packets describe the same delivery.

    Structure equivalence alone is not enough: a later FileDrop delivery can
    use the same spreadsheet layout while requiring its own approval. Stable
    stream/run identities take precedence, with file evidence covering legacy
    packets that predate those identities.
    """

    for attribute in ("raw_stage_key", "backfill_run_id"):
        pending_identity = _identity(pending_packet, attribute)
        approved_identity = _identity(approved_packet, attribute)
        if pending_identity or approved_identity:
            return bool(
                pending_identity
                and approved_identity
                and pending_identity == approved_identity
            )

    identity_fields = (
        "source_file_id",
        "source_file_path",
        "reconciliation_date",
    )
    pending_evidence = tuple(
        (field, _identity(pending_packet, field))
        for field in identity_fields
        if _identity(pending_packet, field) is not None
    )
    approved_evidence = tuple(
        (field, _identity(approved_packet, field))
        for field in identity_fields
        if _identity(approved_packet, field) is not None
    )
    if pending_evidence or approved_evidence:
        return bool(pending_evidence and pending_evidence == approved_evidence)
    return True


__all__ = ["same_review_source_scope"]
