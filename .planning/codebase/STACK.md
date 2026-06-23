# Technology Stack

**Analysis Date:** 2026-06-23

## Languages

- **Python 3.11+:** Primary backend language. All `src/` backend code (`src/`). Type-annotated throughout. Managed via `uv` with `uv.lock` lockfile.
- **TypeScript 5.x:** Frontend language (`frontend-next/src/`). Compiled via Next.js `tsconfig.json` targeting ES2017.
- **JavaScript (ESNext):** Configuration files (`next.config.ts`, `postcss.config.mjs`, `eslint.config.mjs`).

## Runtime

- **Python Runtime:** CPython 3.11-slim (production Docker image: `FROM python:3.11-slim` in `Dockerfile` and `Dockerfile.api`).
- **Node.js Runtime:** Required for frontend development. Managed via npm lockfile (`frontend-next/package-lock.json`).
- **Package Manager (Backend):** `uv` (Python) — `uv.lock` present at project root. Also supports `pip` via `requirements.txt`.
- **Package Manager (Frontend):** npm — `frontend-next/package-lock.json` present.

## Frameworks

- **FastAPI 0.115+:** Backend REST API framework. Application factory pattern: `src/api/__init__.py` `create_app()` function. ASGI server via Uvicorn.
- **Next.js 16.2.9:** Frontend React framework using App Router (`frontend-next/src/app/`). Uses `rewrites()` proxy to backend at `/api/:path*`.
- **React 19.2.4:** Frontend UI library (`frontend-next/`).
- **Tailwind CSS v4:** Frontend styling via `@tailwindcss/postcss` plugin (`frontend-next/postcss.config.mjs`).
- **Pydantic v2+:** Data validation and settings management. Used everywhere in backend: `src/config/settings.py`, `src/analysis/config.py`, `src/analysis/schemas.py`, `src/models/*.py`.
- **Motor 3.0+:** Async MongoDB driver (`motor.motor_asyncio`). Primary database client throughout `src/`.

## Key Dependencies (Backend)

**Critical:**
- `fastapi>=0.115.0` — REST API framework, routes defined in `src/api/*.py`.
- `uvicorn[standard]>=0.30.0` — ASGI server, configured in `Dockerfile.api` and `run.py`.
- `motor>=3.0` — Async MongoDB driver, all repositories use `AsyncIOMotorDatabase`.
- `pydantic>=2.0` / `pydantic-settings>=2.0` — Data models and env configs.
- `httpx>=0.28.1` — Async HTTP client used in `src/fetchers/api_fetcher.py` and `src/analysis/providers/openai_compat.py`.
- `apscheduler>=3.11.2` — Job scheduling with MongoDB job store, `src/scheduler/scheduler.py`.

**Infrastructure & File Handling:**
- `openpyxl>=3.1.0` — Excel file parsing, used in `src/readers/excel_reader.py` and `run.py`.
- `paramiko>=5.0.0` — SFTP client, used in `src/fetchers/sftp_fetcher.py` and `run.py`.
- `cryptography>=48.0.0` — Encryption/decryption for stored credentials (Fernet), `src/fetchers/base.py`.
- `python-decouple>=3.8` — Legacy env variable loading (alongside pydantic-settings).
- `python-multipart>=0.0.18` — File upload support for FastAPI.

**AI/LLM Layer:**
- `httpx` — Used for OpenAI-compatible API calls in `src/analysis/providers/openai_compat.py`.
- No LangChain or similar framework — direct HTTP calls to `/v1/chat/completions` endpoints.

## Key Dependencies (Frontend)

**Production:**
- `next@16.2.9` — Framework.
- `react@19.2.4` / `react-dom@19.2.4` — UI library.

**Dev:**
- `typescript@^5` — Type system.
- `tailwindcss@^4` / `@tailwindcss/postcss@^4` — Styling.
- `eslint@^9` / `eslint-config-next@16.2.9` — Linting.
- `prettier@^3.8.4` / `eslint-config-prettier@^10.1.8` — Formatting.
- `stylelint@^17.13.0` / `stylelint-config-standard@^40.0.0` — CSS linting.
- `@types/node@^20` / `@types/react@^19` / `@types/react-dom@^19` — TypeScript types.

## Configuration

**Environment Variables:**
- Backend uses `pydantic-settings` with `env_prefix="APP_"` in `src/config/settings.py`.
- AI/LLM layer uses separate `AnalysisConfig` with `env_prefix="AI_"` in `src/analysis/config.py`.
- Both load from `.env` file (defined in `SettingsConfigDict(env_file=".env")`).
- `.env.example` documents all 48 required/optional env vars.

**Build Configuration:**
- `pyproject.toml` — Python package metadata, dependencies, ruff config, pytest config.
- `requirements.txt` — Pip-compatible dependency list (used in Docker builds).
- `frontend-next/tsconfig.json` — TypeScript config with `@/*` path alias for `./src/*`.
- `frontend-next/next.config.ts` — Proxies `/api/:path*` to `BACKEND_API_URL`.
- `frontend-next/postcss.config.mjs` — PostCSS with Tailwind CSS v4.
- `frontend-next/.prettierrc` — Prettier formatting config.
- `frontend-next/.stylelintrc.json` — Stylelint CSS linting config.
- `frontend-next/eslint.config.mjs` — ESLint flat config.

**Docker Configuration:**
- `Dockerfile` — Scheduler container. Multi-stage Python 3.11-slim.
- `Dockerfile.api` — API server container. Exposes port 8000, runs `uvicorn`.
- `docker-compose.yml` — Four services: `mongodb`, `sftp`, `mongo-express`, `api`, `scheduler`.
- `docker/init-mongo.js` — MongoDB initialization script (collections, indexes, seed configs).

## Testing

- **pytest 7+** — Test runner, configured in `pyproject.toml` `[tool.pytest.ini_options]`.
- **pytest-asyncio** — Async test support (asyncio_mode = "auto").
- **pytest-cov** — Coverage reporting.
- **ruff** — Linting and formatting (line-length: 100, target-version: py311).
- **mypy** — Type checking (configured but `ignore_errors = true`).

## Project Structure

- **Backend:** Monorepo Python package at `src/`. Enforced via `pyproject.toml` `name = "reconciliation-ingestion"`.
- **Frontend:** Independent Next.js app at `frontend-next/`.
- **Scripts:** Utility scripts in `scripts/`.
- **Tests:** All tests in `tests/` directory (48 test files).
- **Mock data:** `mock_data/`, `test_data/`, `sftp_data/`.

---

*Stack analysis: 2026-06-23*
