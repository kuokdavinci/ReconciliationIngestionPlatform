/qu# Phase 8: Partner Data Fetch Scheduler

## Goal
Implement APScheduler để tự động fetch data từ partner hàng ngày vào 00:00, hỗ trợ 3 phương thức fetch (SFTP, API, FileDrop), và tự động trigger ingestion pipeline sau khi fetch thành công.

## Scope
- ✅ APScheduler integration với MongoDB job store
- ✅ 3 fetch methods riêng biệt: SFTP, API, FileDrop
- ✅ FetchConfig model để cấu hình per-partner
- ✅ Daily cron job (00:00) với configurable schedule
- ✅ Auto-trigger IngestionPipeline sau khi fetch
- ✅ Error handling, retry logic, logging
- ❌ Reconciliation engine (deferred to Phase 9)
- ❌ Compensation workflow (deferred to Phase 10)
- ❌ Dashboard & reporting (deferred to Phase 11)

## Architecture

```
src/
├── scheduler/
│   ├── __init__.py              # Exports: PartnerDataScheduler
│   ├── scheduler.py             # APScheduler setup & lifecycle
│   ├── jobs.py                  # Job definitions (daily fetch job)
│   └── config.py                # Schedule configuration models
│
├── fetchers/
│   ├── __init__.py              # Exports: create_fetcher
│   ├── base.py                  # BaseFetcher abstract class
│   ├── sftp_fetcher.py          # SFTP file fetch (refactor từ run.py)
│   ├── api_fetcher.py           # API data fetch
│   └── filedrop_fetcher.py      # Local file drop watcher
│
├── models/
│   └── fetch_config.py          # FetchConfig model + repository
│
└── ... (existing modules unchanged)
```

## Data Model

### FetchConfig Collection (`fetch_config`)

```json
{
  "_id": "uuid",
  "partner": "MOMO",
  "fetchMethod": "SFTP",
  "enabled": true,
  "schedule": "0 0 * * *",
  "localDownloadDir": "./downloads/MOMO",
  
  "sftp": {
    "host": "sftp.partner.com",
    "port": 22,
    "username": "user",
    "password": "encrypted",
    "remotePath": "/outgoing/reconciliation/*.xlsx"
  },
  
  "api": {
    "baseUrl": "https://api.partner.com/v1/reconciliation",
    "method": "GET",
    "headers": {"Authorization": "Bearer <token>"},
    "queryParams": {"date": "{reconciliation_date}"}
  },
  
  "filedrop": {
    "directory": "/data/partner-drops/MOMO",
    "pattern": "*.xlsx"
  },
  
  "createdAt": "ISODate",
  "updatedAt": "ISODate"
}
```

### Indexes
- `partner` (unique)
- `enabled + fetchMethod` (compound)

## Implementation Plans

### 08-01: FetchConfig Model & Repository
**Files:** `src/models/fetch_config.py`
- FetchConfig pydantic model với 3 fetch method configs
- FetchConfigRepository với các methods: find_by_partner, find_enabled, create, update
- FetchMethod enum: SFTP, API, FILEDROP

### 08-02: BaseFetcher Abstract Class
**Files:** `src/fetchers/base.py`
- Abstract base class với method `async fetch(config: FetchConfig) -> FetchResult`
- FetchResult dataclass: success, local_path, error, metadata
- Common utilities: file validation, cleanup, logging

### 08-03: SFTPFetcher
**Files:** `src/fetchers/sftp_fetcher.py`
- Refactor từ `run.py` SFTP code
- Dùng paramiko (đã có trong dependencies)
- Async wrapper qua `loop.run_in_executor()`
- Download file → `./downloads/{partner}/`
- Support wildcard remote paths
- Connection pooling, timeout handling

### 08-04: APIFetcher
**Files:** `src/fetchers/api_fetcher.py`
- Thêm dependency: `httpx>=0.27` (async HTTP)
- Support GET/POST với custom headers, query params
- Response → lưu thành file Excel/CSV
- Retry với exponential backoff
- Rate limiting support

### 08-05: FileDropFetcher
**Files:** `src/fetchers/filedrop_fetcher.py`
- Thêm dependency: `watchdog>=4.0` (filesystem watcher)
- Watch local directory cho file mới
- Match file pattern
- Debouncing để tránh trigger nhiều lần
- Return local file path

### 08-06: Scheduler Setup
**Files:** `src/scheduler/scheduler.py`, `src/scheduler/config.py`
- APScheduler với AsyncIOScheduler
- MongoDB job store (persist job state)
- AsyncIOExecutor
- Lifecycle management: start, stop, pause, resume
- Config từ MongoDB hoặc defaults

### 08-07: Daily Fetch Job
**Files:** `src/scheduler/jobs.py`
- Cron schedule: `0 0 * * *` (00:00 hàng ngày)
- Flow:
  1. Query `fetch_config` collection → danh sách enabled partners
  2. Với mỗi partner:
     - Tạo appropriate fetcher dựa trên `fetch_method`
     - Gọi `fetcher.fetch(config)`
     - Nếu success → trigger `IngestionPipeline.process_file()`
     - Log kết quả (success/failed)
  3. Aggregate results → emit log events
- Error handling per-partner (failure không block partners khác)
- Retry logic với configurable backoff

### 08-08: Integration & CLI
**Files:** `src/scheduler/__init__.py`, update `run.py`
- Export `PartnerDataScheduler` class
- CLI commands: `--start-scheduler`, `--run-job-now`, `--list-jobs`
- Integration với existing ingestion pipeline
- Structured logging cho scheduler events

### 08-09: Tests
**Files:** `tests/test_fetchers.py`, `tests/test_scheduler.py`
- Unit tests cho từng fetcher (mock SFTP/API/filesystem)
- Integration test cho scheduler job
- Test error scenarios (network failure, invalid config, etc.)
- Test retry logic, debouncing, rate limiting

## Dependencies

### New Python Packages
```toml
"APScheduler>=3.10",
"httpx>=0.27",
"watchdog>=4.0",
```

### Existing Packages (reused)
- `paramiko` - SFTP connections
- `motor` - MongoDB async
- `pydantic` - Data models
- `openpyxl` - Excel file validation

## Error Handling Strategy

| Scenario | Handling |
|----------|----------|
| SFTP connection failed | Log error, retry 3x với 5s delay, mark as failed |
| API timeout | Log error, retry 3x với exponential backoff (1s, 2s, 4s) |
| File drop không có file mới | Log warning, skip silently |
| Ingestion pipeline failure | Mark file as failed, continue với partner khác |
| Scheduler crash | Restart trên next app start (MongoDB job store persists state) |

## Logging Events

| Event | Fields |
|-------|--------|
| SCHEDULER_STARTED | version, job_count |
| SCHEDULER_STOPPED | reason |
| JOB_STARTED | job_id, partner, fetch_method |
| FETCH_SUCCESS | partner, file_path, file_size, duration_ms |
| FETCH_FAILED | partner, error, retry_count |
| INGESTION_TRIGGERED | partner, file_path |
| JOB_COMPLETED | partner, status, duration_ms |

## Migration from run.py

- SFTP code trong `run.py` sẽ được refactor vào `SFTPFetcher`
- `run.py` vẫn giữ nguyên cho manual CLI usage
- Scheduler sẽ dùng fetchers mới thay vì code cũ

## Success Criteria

- [ ] APScheduler chạy đúng với MongoDB job store
- [ ] 3 fetch methods hoạt động độc lập
- [ ] Daily job chạy vào 00:00 (có thể override per-partner)
- [ ] Auto-trigger ingestion pipeline sau fetch success
- [ ] Error handling không block partners khác
- [ ] Structured logging cho tất cả scheduler events
- [ ] CLI commands cho manual trigger và monitoring
- [ ] Unit + integration tests (≥50 tests)
- [ ] Documentation updated

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| APScheduler blocking event loop | Dùng AsyncIOScheduler + AsyncIOExecutor |
| SFTP connection timeout | Configurable timeout, retry logic |
| API rate limiting | Backoff strategy, configurable delays |
| File drop race conditions | Debouncing, file lock checking |
| MongoDB job store corruption | Fallback to memory store, health checks |

## Estimated Effort

| Plan | Complexity | Tests |
|------|-----------|-------|
| 08-01: FetchConfig Model | Low | ~10 |
| 08-02: BaseFetcher | Low | ~5 |
| 08-03: SFTPFetcher | Medium | ~15 |
| 08-04: APIFetcher | Medium | ~15 |
| 08-05: FileDropFetcher | Medium | ~15 |
| 08-06: Scheduler Setup | Medium | ~10 |
| 08-07: Daily Fetch Job | High | ~20 |
| 08-08: Integration & CLI | Low | ~10 |
| 08-09: Tests | Medium | ~20 |
| **Total** | | **~120 tests** |
