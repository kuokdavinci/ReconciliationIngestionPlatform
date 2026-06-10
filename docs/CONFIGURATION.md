# Configuration

## Sources of Truth

Application settings are defined in:

- `src/config/settings.py` for `APP_` variables
- `src/analysis/config.py` for `AI_` variables
- `.env.example` for local bootstrap values
- `docker-compose.yml` for container wiring overrides

## Application Settings

Loaded by `src/config/settings.py`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection string |
| `APP_DB_NAME` | `reconciliation` | Database name |
| `APP_LOG_LEVEL` | `INFO` | Log level |
| `APP_LOG_FORMAT` | `json` | Log output format |
| `APP_APP_NAME` | `reconciliation-ingestion` | Service name |
| `APP_STRICT_MAPPING_APPROVAL_ENABLED` | `true` | Controls strict mapping approval behavior in runtime settings |

## AI Analysis Settings

Loaded by `src/analysis/config.py`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `AI_PROVIDER` | `openai` | Primary LLM provider |
| `AI_MODEL` | `gpt-4o` | Primary model |
| `AI_ENDPOINT` | `https://api.openai.com/v1` | Primary endpoint |
| `AI_API_KEY` | none | Primary provider credential |
| `AI_FALLBACK_PROVIDER` | `openai` | Fallback provider |
| `AI_FALLBACK_MODEL` | `gpt-4o-mini` | Fallback model |
| `AI_FALLBACK_ENDPOINT` | none | Fallback endpoint, defaults to primary if unset |
| `AI_FALLBACK_API_KEY` | none | Fallback API key, defaults to primary if unset |
| `AI_TIMEOUT` | `30` | Request timeout in seconds |
| `AI_MAX_RETRIES` | `2` | Retry attempts |
| `AI_JSON_MODE` | `true` | Structured response mode toggle |
| `AI_CACHE_TTL_SECONDS` | `300` | Insight cache TTL |
| `AI_CACHE_ENABLED` | `true` | In-memory insight cache toggle |
| `AI_ALERT_MISMATCH_RATE_THRESHOLD` | `5.0` | Alert threshold |
| `AI_ALERT_MISSING_COUNT_THRESHOLD` | `10` | Alert threshold |

## Local Bootstrap

Create local config:

```bash
cp .env.example .env
```

`.env.example` currently also carries local Docker/SFTP bootstrap values:

- `MONGO_ROOT_USER`
- `MONGO_ROOT_PASSWORD`
- `SFTP_HOST`
- `SFTP_PORT`
- `SFTP_USER`
- `SFTP_PASS`
- `SFTP_REMOTE_DIR`

These are not loaded by `BaseSettings` directly unless referenced by code or container config, but they are part of the local runtime contract.

## Docker Overrides

`docker-compose.yml` overrides or wires:

- `APP_MONGODB_URL` for `api` and `scheduler`
- `SFTP_HOST=sftp` for the scheduler container
- MongoDB root credentials for the database and Mongo Express

## Mapping Configuration Lifecycle

Runtime mapping configs live in MongoDB and are loaded through `ConfigLoader`.

Relevant modules:

- `src/config/loader.py`
- `src/config/validator.py`
- `src/models/mapping_config.py`

Supported states described in code and docs:

- `PENDING_APPROVAL`
- `APPROVED`
- `REJECTED`
- `SUPERSEDED`

Only approved configs are intended for active runtime loading.

## Review and Automation Documents

Additional persisted configuration-like documents:

- `review_packet`
  - human review state for mapping/runtime changes
- `copilot_action`
  - Copilot recommendation audit trail
- `fetch_config`
  - partner fetch method and schedule definitions

## Notes on Drift

- `.env.example` uses `AI_MODEL=gpt-4o-mini`, while `AnalysisConfig` defaults to `gpt-4o`. Treat the effective value as environment-driven when `.env` is used.
- Keep docs synchronized with settings classes first, then with example env files.
