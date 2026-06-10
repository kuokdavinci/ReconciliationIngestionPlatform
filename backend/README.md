# Backend

This directory is a lightweight backend boundary marker. The active FastAPI application and domain logic still live under `src/`.

## Local Run

Preferred command:

```bash
uv run python run.py --serve --port 8000
```

Direct Uvicorn:

```bash
uv run uvicorn src.api:create_app --factory --host 0.0.0.0 --port 8000
```

## Notes

- The FastAPI app factory is `src.api:create_app`.
- Do not document `backend.app:create_app`; that target does not exist in this repo.
