# Configuration Reference

**Cập nhật:** 2026-08-27

Nguồn sự thật là `src/config/settings.py`, `src/analysis/config.py`, `.env.example` và `docker-compose.yml`.

```bash
cp .env.example .env
```

Không commit secret thật. Local Compose dùng hostname service; process chạy ngoài Docker thường dùng `localhost`.

## Application (`APP_`)

| Biến | Mục đích |
|---|---|
| `APP_MONGODB_URL`, `APP_DB_NAME` | MongoDB config/metadata/workflow |
| `APP_POSTGRES_URL` | PostgreSQL transaction/result |
| `APP_BUSINESS_TIMEZONE` | Business-date boundary; mặc định `Asia/Ho_Chi_Minh` |
| `APP_STRICT_MAPPING_APPROVAL_ENABLED` | Bắt buộc approval mapping; mặc định `true` |
| `APP_AUTOMATION_ORCHESTRATOR` | Workflow provider; mặc định `airflow` |
| `APP_UPLOAD_TMP_DIR` | Temporary mapping upload |
| `APP_INGEST_BATCH_SIZE`, `APP_INGEST_WRITE_WORKERS` | Batch và mức song song khi ghi |
| `APP_INGEST_ORDERED_INSERT` | Ordered/unordered insert |
| `APP_INGESTION_QUARANTINE_RETENTION_DAYS` | TTL quarantine evidence |

Log dùng `APP_LOG_LEVEL` và `APP_LOG_FORMAT`.

## Database và source

| Nhóm | Biến chính |
|---|---|
| MongoDB | `MONGO_ROOT_USER`, `MONGO_ROOT_PASSWORD`, `APP_MONGODB_URL` |
| PostgreSQL | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `APP_POSTGRES_URL` |
| SFTP | `SFTP_HOST`, `SFTP_PORT`, `SFTP_USER`, `SFTP_PASS`, `SFTP_REMOTE_DIR` |

Default local PostgreSQL là `postgresql+asyncpg://postgres:postgres@localhost:5432/reconciliation`.

## Airflow

| Biến | Mục đích |
|---|---|
| `APP_AIRFLOW_BASE_URL`, `APP_AIRFLOW_DAG_ID` | API gọi DAG `reconciliation_ingestion` |
| `APP_AIRFLOW_USERNAME`, `APP_AIRFLOW_PASSWORD` | REST authentication |
| `AIRFLOW_GLOBAL_SCHEDULE` | `none` cho manual-only pilot |
| `AIRFLOW_STREAM_TIMEOUT_SECONDS` | Stream task timeout; mặc định `7200` |
| `AIRFLOW_TASK_RETRIES` | Native task retries; pilot mặc định `0` |
| `AIRFLOW_JWT_SECRET` | Secret dùng chung Airflow services |
| `AIRFLOW_DB_*`, `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` | Airflow metadata database riêng |

Không đưa partner credentials vào DAG `conf` hoặc XCom. Đổi secret mặc định trước production.

## AI analysis (`AI_`)

`AI_PROVIDER`, `AI_MODEL`, `AI_ENDPOINT`, `AI_API_KEY` cấu hình provider chính. `AI_FALLBACK_*` cấu hình fallback; `AI_TIMEOUT`, `AI_MAX_RETRIES`, `AI_JSON_MODE`, `AI_CACHE_*` kiểm soát request/cache. Real LLM E2E cần credential thật; test guardrail/provider dùng fake key.

## Schema và thời gian

```bash
uv run alembic upgrade head
```

PostgreSQL event timestamp là UTC-naive. Business date phải được tính theo `APP_BUSINESS_TIMEZONE`, không theo timezone ngẫu nhiên của container.
