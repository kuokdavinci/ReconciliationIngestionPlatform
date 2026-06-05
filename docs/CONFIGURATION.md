# Configuration Guide

## Environment Variables

All settings use the `APP_` prefix and are loaded via pydantic-settings.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_MONGODB_URL` | string | `mongodb://localhost:27017` | MongoDB connection string |
| `APP_DB_NAME` | string | `reconciliation` | Database name |
| `APP_LOG_LEVEL` | string | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR |
| `APP_LOG_FORMAT` | string | `json` | Log format: `json` or `text` |
| `APP_APP_NAME` | string | `reconciliation-ingestion` | Application name |

### AI Analysis Layer

All settings use the `AI_` prefix and are loaded via pydantic-settings with `AnalysisConfig`.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AI_PROVIDER` | string | `openai` | LLM provider type: `openai` \| `ollama` |
| `AI_MODEL` | string | `gpt-4o` | Model name for the selected provider |
| `AI_ENDPOINT` | string | `https://api.openai.com/v1` | API endpoint URL (OpenAI-compatible format) |
| `AI_API_KEY` | string | — | API key for the LLM provider |
| `AI_TIMEOUT` | int | `30` | HTTP timeout in seconds for LLM calls |
| `AI_MAX_RETRIES` | int | `2` | Maximum retry attempts on failure |
| `AI_ALERT_MISMATCH_RATE_THRESHOLD` | float | `5.0` | Mismatch rate percentage threshold for alerts |
| `AI_ALERT_MISSING_COUNT_THRESHOLD` | int | `10` | Missing transaction count threshold for alerts |

### Setup

```bash
cp .env.example .env
# Edit .env with your values
```

## Mapping Configuration

MappingConfig documents define how partner Excel files are parsed. Stored in `reconciliation_mapping_config` collection.

### Structure

```json
{
  "_id": "<uuid>",
  "partner": "MOMO",
  "workflowType": "UPC",
  "fileType": "SETTLEMENT",
  "sheetName": "Sheet1",
  "startRow": 2,
  "configVersion": "v1",
  "fieldMappings": [...],
  "createdAt": "<ISODate>"
}
```

### Field Mapping Types

#### STRING — Direct string copy

```json
{ "path": "id", "column": 1, "type": "STRING", "required": true }
```

#### DECIMAL — Convert to Decimal (float rejected)

```json
{ "path": "amount", "column": 4, "type": "DECIMAL" }
```

#### DATE — Parse against whitelisted formats

Supported formats: `%Y-%m-%d`, `%d/%m/%Y`, `%Y-%m-%d %H:%M:%S`, `%d/%m/%Y %H:%M:%S`

```json
{ "path": "transDate", "column": 7, "type": "DATE" }
```

#### CONSTANT — Use literal value

```json
{ "path": "currency", "constant": "VND", "type": "CONSTANT" }
```

#### MAPPING — Dict lookup with "others" fallback

```json
{
  "path": "status",
  "column": 17,
  "type": "MAPPING",
  "mapping": {
    "Thành công": "SUCCESS",
    "Thất bại": "FAILED",
    "others": "FAILED"
  }
}
```

### Adding a New Partner

1. Create a MappingConfig document with field mappings
2. Insert into MongoDB (status defaults to `APPROVED` for direct seeding):

```python
from motor.motor_asyncio import AsyncIOMotorClient
from src.models.mapping_config import MappingConfig, MappingConfigRepository, MappingConfigStatus
from src.core.enums import FileType
from src.core.types import FieldMapping, FieldMappingType

client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client["reconciliation"]
repo = MappingConfigRepository(db)

config = MappingConfig(
    partner="VNPAY",
    workflow_type="UPC",
    file_type=FileType.SETTLEMENT,
    sheet_name="Data",
    start_row=3,
    status=MappingConfigStatus.APPROVED,
    field_mappings=[
        FieldMapping(path="id", column=1, type=FieldMappingType.STRING, required=True),
        FieldMapping(path="amount", column=5, type=FieldMappingType.DECIMAL),
        FieldMapping(path="currency", constant="VND", type=FieldMappingType.CONSTANT),
        FieldMapping(
            path="status",
            column=7,
            type=FieldMappingType.MAPPING,
            mapping={"Giao dịch thành công": "SUCCESS", "others": "FAILED"},
        ),
        FieldMapping(path="transDate", column=2, type=FieldMappingType.DATE),
    ],
)

await repo.create(config)
```

3. No code changes needed — the platform reads config dynamically

### Config Status Lifecycle

MappingConfigs now follow a status lifecycle:

```
PENDING_APPROVAL → APPROVED → SUPERSEDED (when new config is approved)
                 → REJECTED
```

- **PENDING_APPROVAL** — AI-generated proposal waiting for human review. Blocked from runtime use.
- **APPROVED** — Active runtime config. Used by `ConfigLoader.load_by_partner_type()`.
- **REJECTED** — Proposal declined by reviewer. Config preserved for audit.
- **SUPERSEDED** — Previously APPROVED config that was replaced by a newer APPROVED config. Kept for version history and rollback.

### Config Versioning

Use `configVersion` field to track config changes:

```json
{
  "partner": "MOMO",
  "workflowType": "UPC",
  "fileType": "SETTLEMENT",
  "configVersion": "v2",
  ...
}
```

Load specific version:
```python
config = await config_loader.load_by_version("MOMO", "v2")
```

## New Collections (Approval & Automation)

### review_packet

Central approval document for every config-change proposal.

| Field | Type | Description |
|-------|------|-------------|
| `_id` | UUID | Packet identifier |
| `sourceType` | string | `UPLOAD` or `SCHEDULER_JOB` |
| `partner` | string | Partner identifier |
| `fileName` | string | Source file name |
| `fileTypeDetected` | string | Detected file type (SETTLEMENT, etc.) |
| `structureSignature` | object | Headers, column count, MD5 of source file |
| `activeRuntimeConfigId` | string | Current approved config ID (if exists) |
| `proposalConfigId` | string | Proposed config ID pending approval |
| `targetActionId` | string | Linked CopilotAction ID |
| `recommendedAction` | object | `{ actionType, reason, confidence }` |
| `parseStrategy` | object | `{ sheetName, startRow, fieldMappingCount, strategy }` |
| `validationGates` | array | `[{ gateKey, label, status, reason }]` |
| `samplePreview` | array | `[{ rowIndex, values }]` first 5 rows |
| `riskSummary` | object | `{ severity, summary }` |
| `runtimeDecisionHint` | string | `KEEP_CURRENT_RUNTIME_UNTIL_APPROVED` or `BLOCK_UNTIL_APPROVED` |
| `status` | string | `PENDING` / `APPROVED` / `REJECTED` / `SUPERSEDED` |
| `decisionMode` | string | `APPROVE_ACTIVATE_NEXT_RUNTIME` / `APPROVE_KEEP_CURRENT_FOR_FILE` / `REJECT` / `SEND_TO_MAPPING_STUDIO` |
| `createdAt` | datetime | Creation timestamp |
| `reviewedAt` | datetime | Review timestamp |
| `reviewedBy` | string | Reviewer identifier |

### copilot_action

Audit trail for AI-generated proposals.

| Field | Type | Description |
|-------|------|-------------|
| `_id` | UUID | Action identifier |
| `type` | string | `MAPPING_PROPOSAL` |
| `partner` | string | Partner identifier |
| `workflowType` | string | Workflow type (e.g. `UPC`) |
| `fileType` | string | File type (e.g. `SETTLEMENT`) |
| `targetConfigId` | string | MappingConfig proposal ID |
| `payload` | object | Proposed mappings, sheet, signature, confidence, reasoning |
| `reason` | string | Human-readable reason for the proposal |
| `status` | string | `PENDING_APPROVAL` / `APPROVED` / `REJECTED` |
| `createdAt` | datetime | Creation timestamp |
| `reviewedAt` | datetime | Review timestamp |

### fetch_config

Scheduler/automation route configuration per partner.

| Field | Type | Description |
|-------|------|-------------|
| `_id` | UUID | Config identifier |
| `partner` | string | Partner identifier |
| `fetchMethod` | string | `SFTP` / `FILEDROP` / `HTTP_POLL` |
| `schedule` | string | Cron expression (e.g. `0 2 * * *`) |
| `enabled` | bool | Whether the job is active |
| `localDownloadDir` | string | Local directory for downloaded files |
| `remotePath` | string | Remote path (SFTP/FILEDROP) |
| `baseUrl` | string | Base URL (HTTP_POLL) |
| `username` | string | Credentials username |
| `encryptedPassword` | string | Credentials password (encrypted) |
| `createdAt` | datetime | Creation timestamp |
| `updatedAt` | datetime | Last update timestamp |

### Adding a new partner with automated fetch

```python
from src.models.fetch_config import FetchConfig, FetchConfigRepository, FetchMethod

config = FetchConfig(
    partner="ACMEPAY",
    fetch_method=FetchMethod.SFTP,
    schedule="0 3 * * *",
    enabled=True,
    local_download_dir="/downloads/acmepay",
    remote_path="/remote/acmepay/incoming/",
    username="sftp_user",
)
await FetchConfigRepository(db).create(config)
```

## MongoDB Indexes

Indexes are defined in `src/models/indexes.py` and applied via `apply_indexes()`.

### reconciliation_file

| Index | Fields | Type | Purpose |
|-------|--------|------|---------|
| `idx_file_hash_unique` | `fileHash` | UNIQUE | Prevent duplicate file ingestion |
| `idx_partner_date` | `partner`, `reconciliationDate` | Compound | Query files by partner and date |

### reconciliation_mapping_config

| Index | Fields | Type | Purpose |
|-------|--------|------|---------|
| `idx_partner_workflow_type` | `partner`, `workflowType`, `fileType` | Compound | Find config by partner/type |

### data_container

| Index | Fields | Type | Purpose |
|-------|--------|------|---------|
| `idx_trace` | `partnerData.trace` | Single | Find transaction by trace |
| `idx_identify_date` | `identify`, `reconciliationDate` | Compound | Duplicate detection key |
| `idx_operation_status` | `operationStatus` | Single | Filter by processing status |
| `idx_partner_status` | `partnerData.status` | Single | Filter by transaction status |
| `idx_source_file` | `sourceFileId` | Single | Find transactions by source file |

### internal_transaction

| Index | Fields | Type | Purpose |
|-------|--------|------|---------|
| `idx_internal_partner_txn_id` | `partnerTxnId` | Single | Fast lookup by reconciliation key |
| `idx_internal_partner_txn_time` | `partner`, `transactionTime` | Compound | Query internal records by partner and date range |

### reconciliation_result

| Index | Fields | Type | Purpose |
|-------|--------|------|---------|
| `idx_recon_partner_txn_id` | `partnerTxnId` | Single | Fast lookup by reconciliation key (for idempotent writes) |
| `idx_recon_status` | `reconciliationStatus` | Single | Filter reconciliation results by status (MATCHED, MISSING, etc.) |

### Additional Collections

| Collection | Index | Type | Purpose |
|-----------|-------|------|---------|
| `review_packet` | `status` | Single | Filter by PENDING/APPROVED/REJECTED |
| `review_packet` | `partner` | Single | Lookup packets by partner |
| `review_packet` | `proposalConfigId` | Single | Link packet to proposal config |
| `copilot_action` | `status` | Single | Filter by approval status |
| `copilot_action` | `partner` | Single | Lookup actions by partner |
| `copilot_action` | `targetConfigId` | Single | Link action to target config |
| `fetch_config` | `partner` | Single (unique) | One config per partner |

### Applying Indexes

```python
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from src.models.indexes import apply_indexes
from src.config.settings import settings

async def main():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    await apply_indexes(db)

asyncio.run(main())
```

MongoDB's `create_indexes` is idempotent — safe to call on every startup.

## Logging Configuration

### JSON Format (default)

```json
{"timestamp": "2026-05-28T10:30:00+00:00", "level": "INFO", "event": "FILE_COMPLETED", "message": "FILE_COMPLETED", "file_id": "abc-123", "total": 1000, "success": 990, "failed": 10, "duration_ms": 2345.67}
```

### Text Format

Set `APP_LOG_FORMAT=text`:

```
[INFO] FILE_COMPLETED: FILE_COMPLETED file_id=abc-123 duration_ms=2345.67 failed=10 success=990 total=1000
```

### Log Level

Set `APP_LOG_LEVEL=DEBUG` for verbose output.
