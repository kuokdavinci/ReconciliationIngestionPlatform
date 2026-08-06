"""Pure date-template helpers shared by ingestion and fetch adapters."""

from datetime import datetime
import re


def interpolate_date(template: str, date: datetime) -> str:
    """Replace ``{date:<format>}`` placeholders with formatted date values."""

    def replace(match: re.Match[str]) -> str:
        return date.strftime(match.group(1) or "%Y%m%d")

    return re.sub(r"\{date:(.*?)\}", replace, template)
