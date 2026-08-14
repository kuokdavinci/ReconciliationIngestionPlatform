"""Recommendation action composition for Copilot dashboard contexts."""

from typing import Any, Optional


def build_recommendation_actions(
    *,
    status: str,
    has_packet: bool,
    has_draft: bool,
    has_runtime: bool,
) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build primary, secondary, and decision actions for a context."""
    secondary: list[dict[str, Any]] = [
        {
            "key": "refresh_context",
            "label": "Refresh recommendation",
            "style": "secondary",
            "enabled": True,
        }
    ]
    primary: Optional[dict[str, Any]] = None
    decision: list[dict[str, Any]] = []

    if status == "healthy":
        return None, secondary, decision

    if has_packet or has_draft:
        primary = {
            "key": "review_proposal",
            "label": "Open Review Center",
            "style": "primary",
            "enabled": True,
        }
        secondary.append(
            {
                "key": "open_mapping_details",
                "label": "Open mapping details",
                "style": "secondary",
                "enabled": True,
            }
        )
        if has_packet:
            decision = [
                {
                    "key": "approve_activate_next_runtime",
                    "label": "Approve activate next runtime",
                    "style": "secondary",
                    "enabled": True,
                },
                {
                    "key": "approve_keep_current",
                    "label": "Keep current",
                    "style": "secondary",
                    "enabled": has_runtime,
                },
                {
                    "key": "reject_proposal",
                    "label": "Reject",
                    "style": "secondary",
                    "enabled": True,
                },
            ]
        return primary, secondary, decision

    label = (
        "Open Mapping Studio"
        if status == "blocked"
        else "Open mapping details or Open file details"
    )
    primary = {
        "key": "open_mapping_details",
        "label": label,
        "style": "primary",
        "enabled": True,
    }
    return primary, secondary, decision
