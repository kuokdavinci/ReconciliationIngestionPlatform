# Configuration Reference

**Cập nhật:** 2026-08-14

## Nguồn sự thật

| Nguồn | Prefix/phạm vi | Vai trò |
|---|---|---|
| `src/config/settings.py` | `APP_` | Runtime settings của FastAPI/application |
| `src/analysis/config.py` | `AI_` | Provider, model, fallback và guardrail analysis |
| `.env.example` | APP/AI/Airflow/DB/SFTP | Bootstrap local và Compose wiring |
| `docker-compose.yml` | Service environment | Override hostname/path giữa container |
| `pyproject.toml`, `requirements-airflow.txt` | Dependencies | API image và Airflow image overlay |

Copy file mẫu trước khi chạy local:

```bash
cp .env.example .env
```

Giá trị trong `.env` có thể override default của Pydantic settings. Không commit secret thật.

## Application (`APP_`)

Các default chính trong `src/config/settings.py`:

| Biến | Default | Mục đích |
|---|---|---|
| `APP_MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection |
| `APP_DB_NAME` | `reconciliation` | Mongo database |
| `APP_POSTGRES_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/reconciliation` | PostgreSQL async connection |
| `APP_LOG_LEVEL` | `INFO` | Log level |
| `APP_LOG_FORMAT` | `json` | Structured log format |
| `APP_APP_NAME` | `reconciliation-ingestion` | Application name |
| `APP_STRICT_MAPPING_APPROVAL_ENABLED` | `true` | Bắt buộc approval theo mapping workflow |
| `APP_UPLOAD_TMP_DIR` | `./scratch/temp_uploads` | Temporary upload directory |
| `APP_AUTOMATION_ORCHESTRATOR` | `airflow` | Workflow provider active |
| `APP_BUSINESS_TIMEZONE` | `Asia/Ho_Chi_Minh` | Business-date boundary |

### Ingestion tuning

| Biến | Default | Mục đích |
|---|---:|---|
| `APP_INGEST_BATCH_SIZE` | `20000` | Batch size khi ghi ingestion |
| `APP_INGEST_WRITE_WORKERS` | `2` | Số worker ghi batch |
| `APP_INGEST_ORDERED_INSERT` | `false` | Ordered hay unordered insert |
| `APP_INGESTION_QUARANTINE_RETENTION_DAYS` | `30` | Số ngày giữ sanitized quarantine evidence trước TTL cleanup |

### Reconciliation tuning

| Biến | Default | Mục đích |
|---|---:|---|

## Database và source connector

| Nhóm | Biến | Mục đích |
|---|---|---|
| MongoDB | `MONGO_ROOT_USER`, `MONGO_ROOT_PASSWORD` | Credentials cho Compose MongoDB |
| PostgreSQL | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Application database bootstrap |
| SFTP | `SFTP_HOST`, `SFTP_PORT`, `SFTP_USER`, `SFTP_PASS`, `SFTP_REMOTE_DIR` | SFTP fetcher và local SFTP service |

Trong Compose, API dùng hostname `mongodb`, `postgres`; Airflow scheduler dùng `SFTP_HOST=sftp`. Local process ngoài Docker thường dùng `localhost`, `27017`, `5432` và `2222` theo `.env.example`.

## Airflow

### Airflow control plane

| Biến | Default trong Compose/example | Mục đích |
|---|---|---|
| `APP_AIRFLOW_BASE_URL` | `http://airflow-api-server:8080` | API → Airflow REST |
| `APP_AIRFLOW_DAG_ID` | `reconciliation_ingestion` | DAG được submit |
| `APP_AIRFLOW_USERNAME` / `APP_AIRFLOW_PASSWORD` | Lấy từ Airflow admin | API authentication |
| `APP_AIRFLOW_REQUEST_TIMEOUT_SECONDS` | `15` trong example | REST request timeout |
| `AIRFLOW_GLOBAL_SCHEDULE` | `none` | Manual-only pilot khi `none` |
| `AIRFLOW_STREAM_TIMEOUT_SECONDS` | `7200` | Stream task timeout |
| `AIRFLOW_TASK_RETRIES` | `0` | Native retry budget |
| `AIRFLOW_TASK_RETRY_DELAY_SECONDS` | `300` | Delay nếu native retry được bật |
| `AIRFLOW_ADMIN_USERNAME` | `airflow` | Local admin |
| `AIRFLOW_ADMIN_PASSWORD` | Example placeholder | Local admin password |
| `AIRFLOW_JWT_SECRET` | Example placeholder | JWT secret dùng chung Airflow services |

Sprint 2.5 manual pilot giữ `AIRFLOW_GLOBAL_SCHEDULE=none` và `AIRFLOW_TASK_RETRIES=0`. `AIRFLOW_JWT_SECRET` phải thay bằng secret ngẫu nhiên đủ dài trước production và giống nhau trên API server, scheduler, DAG processor.

### Airflow database

| Biến | Mục đích |
|---|---|
| `AIRFLOW_DB_USER` | User metadata database |
| `AIRFLOW_DB_PASSWORD` | Password metadata database |
| `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` | Connection do Compose dựng cho Airflow |

Airflow metadata database là database `airflow` riêng, không dùng các bảng application để lưu DAG state.

## AI analysis (`AI_`)

Default trong `src/analysis/config.py`:

| Biến | Default | Mục đích |
|---|---|---|
| `AI_PROVIDER` | `openai` | Primary provider |
| `AI_MODEL` | `gpt-4o` | Primary model |
| `AI_ENDPOINT` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `AI_API_KEY` | unset | Primary credential |
| `AI_FALLBACK_PROVIDER` | `openai` | Fallback provider |
| `AI_FALLBACK_MODEL` | `gpt-4o-mini` | Fallback model |
| `AI_FALLBACK_ENDPOINT` | unset | Fallback endpoint, dùng primary nếu trống |
| `AI_FALLBACK_API_KEY` | unset | Fallback key, dùng primary nếu trống |
| `AI_TIMEOUT` | `30` | Request timeout giây |
| `AI_MAX_RETRIES` | `2` | Retry provider |
| `AI_JSON_MODE` | `true` | Structured JSON output |
| `AI_CACHE_TTL_SECONDS` | `300` | Insight cache TTL |
| `AI_CACHE_ENABLED` | `true` | Bật in-memory cache |

`.env.example` có thể đặt model/key khác cho demo. Không cần real `AI_API_KEY` cho các test guardrail/provider dùng fake key; real LLM E2E cần secret riêng.

## Database migration và startup

```bash
uv run alembic upgrade head
uv run python run.py --serve --port 8000
```

FastAPI lifespan khởi tạo Mongo client/index và gọi initialization cho PostgreSQL. Schema revision chính nằm trong `alembic/versions/`; không dùng tài liệu này làm thay thế migration history.

## Quy tắc an toàn

- Không đưa partner credential vào DAG source, REST `conf` hoặc XCom; chỉ truyền identifier/correlation cần thiết.
- Không dùng default password/JWT secret ngoài local development.
- Timestamps event PostgreSQL là UTC-naive; business date không được suy ra bằng local timezone của container.
- Thay đổi cấu hình Airflow retry/schedule phải đi kèm acceptance test vì có thể thay đổi execution ownership.
