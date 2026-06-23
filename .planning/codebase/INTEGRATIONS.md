# External Integrations

**Analysis Date:** 2026-06-23

## Data Storage

**MongoDB 7.0 (Primary Database):**
- **Role:** All persistent storage — reconciliation data, file records, mapping configs, scheduler jobs, audit logs, automation state.
- **Connection:** Configured via `APP_MONGODB_URL` env var in `src/config/settings.py`.
- **Client:** `motor.motor_asyncio.AsyncIOMotorClient` — async driver used throughout `src/models/repository.py`, `src/api/__init__.py`, `run.py`.
- **Docker:** `mongo:7` image in `docker-compose.yml` with persistent volume `mongo_data`.
- **Management UI:** `mongo-express` on port 8081.
- **Collections:** `reconciliation_file`, `reconciliation_mapping_config`, `data_container`, `reconciliation_result`, `internal_transaction`, `fetch_config`, `apscheduler_jobs`, `audit_events`, `copilot_actions`, `review_packets`, `partner_runtime_runs`, `post_approval_runs`, and others.
- **Indexes:** Created on startup via `src/models/indexes.py` and `docker/init-mongo.js` (unique file hash index, compound partner+date indexes, etc.).
- **Seed Data:** Default MOMO and VNPAY mapping configs inserted in `docker/init-mongo.js`.

**No other databases or caches detected.** No Redis, PostgreSQL, or external cache. The AI insight cache is in-memory (`src/analysis/cache.py` — thread-safe TTL cache).

## APIs & External Services

**OpenAI-Compatible LLM API (AI Analysis Layer):**
- **Purpose:** AI-powered reconciliation insight generation — summary analysis, discrepancy detection, anomaly classification.
- **SDK/Client:** No SDK — direct `httpx.AsyncClient` calls to `/v1/chat/completions` endpoint in `src/analysis/providers/openai_compat.py`.
- **Default Endpoint:** `https://api.openai.com/v1` (configurable via `AI_ENDPOINT` env var).
- **Default Model:** `gpt-4o` primary, `gpt-4o-mini` fallback (configurable via `AI_MODEL` / `AI_FALLBACK_MODEL`).
- **Auth:** Bearer token via `AI_API_KEY` env var.
- **Fallback Chain:** Primary → fallback provider → rule-based (configured in `src/analysis/provider.py` `AIProviderRouter`).
- **JSON Mode:** Enabled by default (`AI_JSON_MODE=true`) for structured output parsing.
- **Timeout/Retry:** 30s timeout, 2 retries (`AI_TIMEOUT`, `AI_MAX_RETRIES`).
- **Cost Tracking:** Built-in USD cost estimation via model-specific rates in `src/analysis/providers/openai_compat.py`.
- **Ollama Support:** Declared in config but `NotImplementedError` — only OpenAI-compatible endpoints work in practice.

**Partner APIs (Data Fetcher):**
- **Purpose:** Fetching partner settlement data via HTTP APIs (GET/POST).
- **Client:** `httpx.AsyncClient` in `src/fetchers/api_fetcher.py`.
- **Configuration:** Stored per-partner in MongoDB `fetch_config` collection (`APIConfig` model in `src/models/fetch_config.py`).
- **Features:** Custom headers, query params, date interpolation, exponential backoff retry (3 retries, 2x multiplier).
- **Auth:** Supports `env:VAR_NAME` resolution and Fernet-encrypted credentials.

## File Transfer

**SFTP Server:**
- **Purpose:** Downloading partner settlement files from external SFTP servers.
- **Client:** `paramiko.SSHClient` with `AutoAddPolicy` in `src/fetchers/sftp_fetcher.py` and `run.py`.
- **Docker:** `atmoz/sftp` image in `docker-compose.yml`, port 2222, credentials via `SFTP_USER`/`SFTP_PASS`.
- **Configuration:** Per-partner `SFTPConfig` in `src/models/fetch_config.py` (host, port, username, password, remote_path, timeout).
- **Features:** Date interpolation in remote paths, wildcard/glob pattern matching, credential resolution (`env:` and `encrypted:`).
- **Local Fallback:** If SFTP fails, falls back to `./sftp_data/` directory.

**Local File Drop:**
- **Purpose:** Scanning local directories for partner files (scheduled scan, no watchdog daemon).
- **Implementation:** `src/fetchers/filedrop_fetcher.py` — glob-based scanning with file-lock stability check.
- **Use Case:** For partners who drop files directly on the server.

## Scheduler

**APScheduler with MongoDB Job Store:**
- **Purpose:** Scheduling daily partner data fetch jobs.
- **Implementation:** `src/scheduler/scheduler.py` — `AsyncIOScheduler` with `MongoDBJobStore`.
- **Job Storage:** MongoDB collection `apscheduler_jobs` (persistent across restarts).
- **Default Schedule:** Daily at midnight (`0 0 * * *`), configurable per-partner in `FetchConfig.schedule`.
- **Memory Fallback:** `MemoryJobStore` if MongoDB is unavailable.
- **Event Hooks:** `on_job_executed` and `on_job_error` callbacks for observability.

## Authentication & Identity

- **No external auth provider.** No OAuth, SSO, or JWT-based auth detected.
- **Actor-based identity:** Frontend uses a simple `X-Actor` header pattern in `frontend-next/src/lib/api/client.ts` via `getCurrentActor()` from `frontend-next/src/lib/actor.ts`. This is a lightweight mechanism for tracking who performed actions in the audit log.
- **No user authentication or session management.** The system assumes trusted internal network access.

## Monitoring & Observability

**Logging:**
- **Structured JSON logging** via custom logger in `src/logging/logger.py`. Configurable via `APP_LOG_LEVEL` and `APP_LOG_FORMAT`.
- **Event-based logging** with structured extra fields throughout — every AI insight generation, reconciliation run, and error has an `event` field key (e.g., `ai_insight_observation`, `reconciliation_started`).
- **No external log aggregation** (no Datadog, Sentry, ELK, etc.).

**Error Tracking:**
- **None detected.** No Sentry, Rollbar, or similar error tracking integration.

**AI Observability:**
- Built-in `AIObservation` schema in `src/analysis/schemas.py` tracks: latency, token counts, estimated cost, cache hits, resolution path, guardrail results. Logged as structured events.
- In-memory `TTLCache` in `src/analysis/cache.py` for AI insight deduplication (5-min default TTL).

## CI/CD & Deployment

**Docker Compose (Development/Production):**
- `docker-compose.yml` defines 5 services: `mongodb`, `sftp`, `mongo-express`, `api`, `scheduler`.
- The `api` service runs `uvicorn src.api:create_app --factory` on port 8000.
- The `scheduler` service runs `python run.py --start-scheduler`.
- Volumes: `./downloads`, `./sftp_data`, `mongo_data`.
- Environment: Loaded from `.env` file and inline `APP_MONGODB_URL` override.

**Dockerfiles:**
- `Dockerfile` — Scheduler container (copies `src/` and `run.py`).
- `Dockerfile.api` — API container (exposes 8000, runs uvicorn).

**Docker Init:**
- `docker/init-mongo.js` — Creates collections, indexes, and default MOMO/VNPAY configs on first boot.

**No CI pipeline detected.** No GitHub Actions, Jenkins, or similar configuration found.

**No production deployment configuration.** No Kubernetes manifests, Helm charts, or cloud-specific deployment configs.

## Environment Configuration

**Required env vars (from `.env.example`):**

| Variable | Purpose | Default |
|---|---|---|
| `MONGO_ROOT_USER` | MongoDB admin user | `admin` |
| `MONGO_ROOT_PASSWORD` | MongoDB admin password | — |
| `APP_MONGODB_URL` | MongoDB connection string | `mongodb://admin:pass@localhost:27017/reconciliation?authSource=admin` |
| `APP_DB_NAME` | Database name | `reconciliation` |
| `APP_LOG_LEVEL` | Logging level | `INFO` |
| `APP_LOG_FORMAT` | Log format | `json` |
| `SFTP_HOST` | SFTP server host | `localhost` |
| `SFTP_PORT` | SFTP server port | `2222` |
| `SFTP_USER` | SFTP username | `foo` |
| `SFTP_PASS` | SFTP password | — |
| `AI_PROVIDER` | LLM provider type | `openai` |
| `AI_MODEL` | LLM model | `gpt-4o-mini` |
| `AI_ENDPOINT` | LLM API endpoint | `https://api.openai.com/v1` |
| `AI_API_KEY` | LLM API key | — |
| `BACKEND_API_URL` | Frontend proxy target | `http://localhost:8000` |

**Secrets:** Stored in `.env` file (not committed). Credentials for SFTP and AI API. Local dev uses `.env` at project root. Docker Compose loads via `env_file: .env`.

## Webhooks & Callbacks

**Incoming Webhooks:**
- **None detected.**

**Outgoing Webhooks:**
- **None detected.** No external notification systems, no Slack/email/PagerDuty integrations.

## Third-Party Services Summary

| Service | Usage | Configuration |
|---|---|---|
| MongoDB 7.0 | Primary database | `APP_MONGODB_URL`, `docker-compose.yml` |
| OpenAI API | AI insight generation (GPT-4o) | `AI_*` env vars |
| SFTP (atmoz) | File transfer for partner data | `SFTP_*` env vars |
| mongo-express | DB admin UI (dev only) | `docker-compose.yml` port 8081 |

---

*Integration audit: 2026-06-23*
