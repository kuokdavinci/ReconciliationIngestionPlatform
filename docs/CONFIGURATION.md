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
2. Insert into MongoDB:

```python
from motor.motor_asyncio import AsyncIOMotorClient
from src.models.mapping_config import MappingConfig, MappingConfigRepository
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
