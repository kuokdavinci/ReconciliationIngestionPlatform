# Module Documentation

## src/core/

### enums.py

```python
class ProcessingStatus(StrEnum):
    PENDING | PROCESSING | COMPLETED | FAILED

class TransactionStatus(StrEnum):
    SUCCESS | FAILED | PENDING | REVERSED

class FileType(StrEnum):
    SETTLEMENT | RECONCILIATION
```

### types.py

```python
class FieldMappingType(StrEnum):
    STRING | DECIMAL | DATE | CONSTANT | MAPPING

class FieldMapping(BaseModel):
    path: str                          # Canonical field name
    column: Optional[Union[int, str]]  # 1-based column number (int preferred) or Excel letter
    sourceField: Optional[str]         # Alternative source field name for documentation
    type: FieldMappingType             # Conversion type
    required: bool                     # Whether this field is mandatory
    constant: Optional[str]            # Value for CONSTANT type
    mapping: Optional[dict[str, str]]  # Value map for MAPPING type

class CanonicalTransaction(BaseModel):
    id: str                            # Partner transaction ID (required)
    trace: Optional[str]               # Transaction reference
    amount: Decimal                    # Monetary value (float rejected)
    currency: str                      # Currency code (e.g., "VND")
    status: TransactionStatus          # Normalized status
    transDate: Optional[datetime]      # Transaction time
    extra: dict[str, Any]              # Additional partner-specific data

class PartnerData(BaseModel):
    # Same fields as CanonicalTransaction but with raw partner status string
    # amount: Decimal (float rejected)

class ValidationError(BaseModel):
    field: str                         # Which field failed
    reason: str                        # Why it failed
    row: Optional[int]                 # Row number for context
    trace: Optional[str]               # Transaction trace for context

class ProcessingStats(BaseModel):
    total_rows: int
    success_rows: int
    failed_rows: int
```

### constants.py

```python
DUPLICATE_KEY_PATTERN = "identify + reconciliationDate + trace"
FILE_HASH_KEY = "fileHash"
DEFAULT_CURRENCY = "VND"
MAX_FILE_SIZE_MB = 50
LOG_FORMATS = {"json", "text"}
```

---

## src/config/

### settings.py

```python
class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    db_name: str = "reconciliation"
    log_level: str = "INFO"
    log_format: str = "json"
    app_name: str = "reconciliation-ingestion"

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

settings = Settings()
```

### cache.py

```python
class ConfigCache:
    DEFAULT_TTL = 300  # 5 minutes

    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[MappingConfig]
    def put(self, key: str, config: MappingConfig, ttl_seconds: int = 300) -> None
    def invalidate(self, key: str) -> None
    def clear(self) -> None
```

**Thread safety:** All operations protected by `threading.Lock`. Lazy cleanup on `get()` — expired entries removed on access, no background threads.

### validator.py

```python
class ConfigValidator:
    @staticmethod
    def validate(config: MappingConfig) -> list[ConfigValidationError]
    @staticmethod
    def validate_required_coverage(config: MappingConfig, required_paths: set[str]) -> list[ConfigValidationError]
```

**Validation checks:**
1. Empty `field_mappings` array
2. Duplicate `path` values
3. CONSTANT type without `constant` value
4. MAPPING type without `mapping` dict
5. Required field without `column` or `constant`
6. Invalid column format (only validated when column is string — must be uppercase letters; int columns skip this check)

### loader.py

```python
class ConfigLoader:
    def __init__(self, repository: MappingConfigRepository, cache: ConfigCache,
                 validator: ConfigValidator, default_ttl: int = 300) -> None

    async def load_by_partner_type(self, partner, workflow_type, file_type,
                                   required_paths=None) -> MappingConfig
    async def load_by_version(self, partner, version, required_paths=None) -> MappingConfig
    def invalidate_cache(self, key: str) -> None
```

**Flow:** cache check → DB query → validate → cache → return

---

## src/readers/

### excel_reader.py

```python
class ExcelStreamReader:
    DEFAULT_SKIP_PATTERNS = ["total", "grand total", "summary", "footer", "合计", "总计", "小计"]

    def __init__(self, file_path, *, sheet_name=None, sheet_index=None,
                 start_row=1, skip_empty_rows=True, skip_patterns=None) -> None

    @classmethod
    def from_mapping_config(cls, file_path, config: MappingConfig) -> ExcelStreamReader

    def __enter__(self) -> Self
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool
    def get_sheet_names(self) -> list[str]
    def iter_rows(self) -> Iterator[tuple]
```

**Key behaviors:**
- `read_only=True` for constant memory
- Context manager required — raises `RuntimeError` if used outside
- `_is_empty_row()`: all cells None or ""
- `_should_skip_row()`: empty row check + pattern match (case-insensitive)
- `from_mapping_config()`: uses `config.sheet_name` and `config.start_row`

---

## src/normalizer/

### normalizer.py

```python
class TransactionNormalizer:
    _DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S")

    def __init__(self, field_mappings: list[FieldMapping]) -> None
    def normalize(self, row: tuple, row_number=None) -> NormalizationResult
    @staticmethod
    def build_canonical(data: dict, errors: list, row_number=None) -> tuple[CanonicalTransaction | None, list[ValidationError]]
```

**Key behaviors:**
- `normalize()` accepts row tuples directly (not dicts) — uses `FieldMapping.column` (1-based int) to index into tuple
- `_resolve_source()` handles both int column numbers and string column letters with automatic conversion:
  - int column → direct tuple index (col - 1)
  - string digit → converted to int, then indexed
  - string letter → converted via `column_index_from_string()`, then indexed
  - dict rows → supports both int and string keys with fallback conversion
- `build_canonical()` handles dot-separated paths: `"extra.service"` → `extra["service"] = value`
- Required fields validated: id, amount, currency, status
- Extra fields (keys not in canonical schema) collected into `extra` dict

---

## src/validators/

### validator.py

```python
class Validator:
    def __init__(self, data_container_repo=None, reconciliation_file_repo=None)

    def validate(self, txn: CanonicalTransaction, row_number=None, trace=None) -> ValidationResult
    async def validate_with_duplicates(self, txn, identify, reconciliation_date,
                                       file_hash=None, row_number=None, trace=None) -> ValidationResult
```

**Validation rules:**

| Rule | Check | Error reason |
|------|-------|-------------|
| Required id | `txn.id` non-empty | "required field 'id' is empty or missing" |
| Required currency | `txn.currency` non-empty | "required field 'currency' is empty or missing" |
| Decimal non-negative | `txn.amount >= 0` | "amount must be non-negative" |
| Date type | `txn.transDate` is datetime | "transDate must be a datetime object" |
| Status enum | `txn.status` in TransactionStatus | "invalid status value" |
| Transaction duplicate | identify + reconciliationDate + trace exists | "transaction already exists" |
| File duplicate | fileHash exists | "file already processed" |

**Note:** Pipeline uses `validate()` (core validation only) since file duplicate is checked at pipeline level before row processing. `validate_with_duplicates()` is available for standalone use.

---

## src/models/

### repository.py

```python
class BaseRepository(Generic[T]):
    def __init__(self, collection_name: str, db: AsyncIOMotorDatabase)
    async def create(self, doc: T) -> T
    async def find_one(self, query: dict) -> Optional[T]
    async def find_many(self, query: dict) -> list[T]
    async def update_one(self, query: dict, update: dict) -> bool
    async def delete_one(self, query: dict) -> bool

    def _to_mongo(self, doc: T) -> dict       # Converts UUIDs→str, Decimals→Decimal128
    @staticmethod
    def _convert_special_types(obj: Any) -> Any  # Recursive type conversion
```

**Key behaviors:**
- `_to_mongo()` calls `model_dump(by_alias=True, exclude_none=False)` then `_convert_special_types()`
- `_convert_special_types()` recursively handles: UUID→str, Decimal→Decimal128, nested dicts/lists
- `_from_mongo()` converts raw MongoDB docs to pydantic models, converts `_id` ObjectId to string

### reconciliation_file.py

```python
class ReconciliationFileRepository(BaseRepository[ReconciliationFile]):
    async def find_by_file_hash(self, file_hash: str) -> Optional[ReconciliationFile]
    async def find_by_partner_and_date(self, partner, reconciliation_date) -> list[ReconciliationFile]
    async def update_processing_stats(self, file_id, total, success, failed) -> bool
    async def update_status(self, file_id, status: ProcessingStatus) -> bool
```

### mapping_config.py

```python
class MappingConfigRepository(BaseRepository[MappingConfig]):
    async def find_by_partner_and_type(self, partner, workflow_type, file_type) -> Optional[MappingConfig]
    async def find_by_version(self, partner, version) -> Optional[MappingConfig]
```

### data_container.py

```python
class DataContainerRepository(BaseRepository[DataContainer]):
    async def insert_many(self, docs: list[DataContainer]) -> int
    async def find_by_trace(self, identify, trace) -> Optional[DataContainer]
    async def find_by_source_file(self, source_file_id) -> list[DataContainer]
    async def find_by_date_range(self, identify, start, end) -> list[DataContainer]
    async def find_by_duplicate_key(self, identify, reconciliation_date, trace) -> Optional[DataContainer]
```

### indexes.py

```python
INDEXES: dict[str, list[IndexModel]] = {
    "reconciliation_file": [
        IndexModel("fileHash", unique=True),
        IndexModel([("partner", ASCENDING), ("reconciliation_date", ASCENDING)]),
    ],
    "reconciliation_mapping_config": [
        IndexModel([("partner", ASCENDING), ("workflow_type", ASCENDING), ("file_type", ASCENDING)]),
    ],
    "data_container": [
        IndexModel("partnerData.trace"),
        IndexModel([("identify", ASCENDING), ("reconciliationDate", ASCENDING)]),
        IndexModel("operationStatus"),
        IndexModel("partnerData.status"),
        IndexModel("sourceFileId"),
    ],
}

async def apply_indexes(db: AsyncIOMotorDatabase) -> None
```

---

## src/pipeline/

### ingestion_pipeline.py

```python
class IngestionPipeline:
    def __init__(self, db, config_loader: ConfigLoader, batch_size: int = 100,
                 logger: StructuredLogger | None = None) -> None

    async def process_file(self, file_path, partner, workflow_type, file_type,
                           reconciliation_date, config_version=None) -> IngestionResult
```

**Key behaviors:**
- `_compute_file_hash()` — SHA256 hash via thread pool executor
- File duplicate checked once at pipeline level (not per-row)
- Row tuples passed directly to normalizer (no tuple→dict conversion)
- Uses `validator.validate()` (core validation only) — file duplicate already checked
- `_flush_batch()` — calls `DataContainerRepository.insert_many()`
- `_to_mongo()` used in `insert_many()` for UUID/Decimal conversion
- Per-row errors never stop the pipeline
- Exception at any level → status FAILED, partial stats returned

---

## src/logging/

### logger.py

```python
class StructuredLogger:
    def __init__(self, name: str = "reconciliation") -> None

    def emit_file_started(self, file_id, file_name, partner) -> None
    def emit_file_completed(self, file_id, total, success, failed, duration_ms) -> None
    def emit_file_failed(self, file_id, error) -> None
    def emit_row_success(self, file_id, row_number, trace) -> None
    def emit_row_failed(self, file_id, row_number, trace, reason) -> None

def get_structured_logger(name: str = "reconciliation") -> StructuredLogger
```

**JSON output example:**
```json
{
  "timestamp": "2026-05-28T10:30:00+00:00",
  "level": "INFO",
  "event": "FILE_COMPLETED",
  "message": "FILE_COMPLETED",
  "file_id": "abc-123",
  "total": 1000,
  "success": 990,
  "failed": 10,
  "duration_ms": 2345.67
}
```
