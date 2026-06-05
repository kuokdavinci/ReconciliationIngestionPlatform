# Backend

Backend entry surface for the AdapterService API.

## Run

```bash
uv run python run.py serve --port 8000
```

Or directly through Uvicorn:

```bash
uv run uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8000
```

## Notes

- Core FastAPI routers and domain logic still live under `src/`.
- This directory exists to give the project a clear backend boundary next to `frontend/`.
