"""Backend application surface for AdapterService.

Keeps the API entrypoint distinct from the frontend workspace while reusing
the existing FastAPI factory in ``src.api``.
"""

from src.api import create_app

__all__ = ["create_app"]
