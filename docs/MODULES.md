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

class ReconciliationStatus(StrEnum):
    MATCHED | AMOUNT_MISMATCH | STATUS_MISMATCH |
    MULTIPLE_MISMATCH | MISSING_INTERNAL | MISSING_PARTNER
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

### internal_transaction.py

```python
class InternalTransaction(BaseModel):
    id: str = Field(alias="_id")              # internalTxnId
    partner: str                              # MOMO, ZALOPAY, etc.
    partner_txn_id: str = Field(alias="partnerTxnId")  # reconciliation key
    amount: Decimal                           # float rejected at pydantic level
    currency: str = "VND"
    status: TransactionStatus
    transaction_time: datetime = Field(alias="transactionTime")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

class InternalTransactionRepository(BaseRepository[InternalTransaction]):
    async def insert_many(self, docs: list[InternalTransaction]) -> int
    async def find_by_partner_and_date_range(self, partner, start, end) -> list[InternalTransaction]
```

### reconciliation_result.py

```python
class ReconciliationResult(BaseModel):
    id: str = Field(alias="_id")                           # partnerTxnId
    partner_txn_id: str = Field(alias="partnerTxnId")
    internal_txn_id: Optional[str] = Field(alias="internalTxnId")
    partner_amount: Optional[Decimal] = Field(alias="partnerAmount")
    internal_amount: Optional[Decimal] = Field(alias="internalAmount")
    partner_status: Optional[str] = Field(alias="partnerStatus")
    internal_status: Optional[str] = Field(alias="internalStatus")
    reconciliation_status: ReconciliationStatus = Field(alias="reconciliationStatus")
    partner_record_id: Optional[str] = Field(alias="partnerRecordId")
    internal_record_id: Optional[str] = Field(alias="internalRecordId")
    created_at: datetime = Field(alias="createdAt")

class ReconciliationResultRepository(BaseRepository[ReconciliationResult]):
    async def insert_many(self, docs: list[ReconciliationResult]) -> int
```

### indexes.py

```python
INDEXES: dict[str, list[IndexModel]] = {
    "reconciliation_file": [
        IndexModel("fileHash", unique=True),
        IndexModel([("partner", ASCENDING), ("reconciliationDate", ASCENDING)]),
    ],
    "reconciliation_mapping_config": [
        IndexModel([("partner", ASCENDING), ("workflowType", ASCENDING), ("fileType", ASCENDING)]),
    ],
    "data_container": [
        IndexModel("partnerData.trace"),
        IndexModel([("identify", ASCENDING), ("reconciliationDate", ASCENDING)]),
        IndexModel("operationStatus"),
        IndexModel("partnerData.status"),
        IndexModel("sourceFileId"),
    ],
    "internal_transaction": [
        IndexModel("partnerTxnId"),
        IndexModel([("partner", ASCENDING), ("transactionTime", ASCENDING)]),
    ],
    "reconciliation_result": [
        IndexModel("partnerTxnId"),
        IndexModel("reconciliationStatus"),
    ],
}

async def apply_indexes(db: AsyncIOMotorDatabase) -> None
```

---

## src/analysis/

### config.py

```python
class AnalysisConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = "openai"              # LLM provider type: openai | ollama
    model: str = "gpt-4o"                 # Model name
    endpoint: str = "https://api.openai.com/v1"
    api_key: Optional[str] = None
    timeout: int = 30                     # HTTP timeout in seconds
    max_retries: int = 2                  # Maximum retry attempts
    alert_mismatch_rate_threshold: float = 5.0
    alert_missing_count_threshold: int = 10

    @property
    def provider_type(self) -> str:
        return self.provider.lower()
```

### provider.py

```python
class LLMProvider(Protocol):
    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str: ...

def create_provider(config: AnalysisConfig) -> LLMProvider:
    # Routes to OpenAICompatProvider or OllamaProvider based on config.provider_type
```

### providers/openai_compat.py

```python
class OpenAICompatProvider:
    def __init__(self, config: AnalysisConfig) -> None
        # Uses httpx.AsyncClient, retry logic, low temperature (0.1)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        # POST {endpoint}/v1/chat/completions with OpenAI-compatible body
        # Parse response.choices[0].message.content
```

### schemas.py

```python
class GroupCriteria(BaseModel):
    status: Optional[str] = None
    partner: Optional[str] = None
    amount_range_min: Optional[Decimal] = None
    amount_range_max: Optional[Decimal] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None

class GroupResult(BaseModel):
    key: str
    count: int
    percentage: float
    total_amount: Decimal
    details: dict[str, Any] = {}

class SummaryResult(BaseModel):
    partner: str
    date: str
    total_transactions: int
    matched: int
    mismatch_rate: float
    total_amount_mismatch: Decimal
    by_status: dict[str, int]
    total_volume: Decimal
    avg_mismatch_amount: Decimal

class AnalysisResult(BaseModel):
    type: str
    severity: str          # low, medium, high, critical
    title: str
    description: str
    affected_count: int
    recommendation: str

class TopAnomaly(BaseModel):
    type: str
    count: int
    partners_affected: list[str]
    amount_range: str

class AnalysisInput(BaseModel):
    """Privacy-by-design: no raw transaction data, only aggregated metrics."""
    partner: str
    date: str
    focus: str             # operational | partner | inconsistency
    summary_metrics: dict[str, Any]
    grouped_stats: list[GroupResult]
    top_anomalies: list[TopAnomaly]
```

### grouping.py

```python
class GroupingEngine:
    def group(self, results: list, criteria: GroupCriteria) -> list[GroupResult]:
        # Pure function: group by reconciliationStatus, amount_range, partner
        # Amount ranges: 0-100k, 100k-1M, 1M+
        # Deterministic, no IO
```

### metrics.py

```python
class MetricsService:
    @staticmethod
    def compute_summary(results: list, partner: str, date: str) -> SummaryResult:
        # Single source of truth for all stats
        # mismatch_rate %, total_volume, avg_mismatch_amount, count_by_status

    @staticmethod
    def summary_from_groups(groups: list[GroupResult], results: list) -> dict:
        # Cross-group stats
```

### prompts.py

```python
def build_system_prompt() -> str:
    # Defines AI analysis assistant role, constraints, JSON output format

def build_analysis_prompt(analysis_input: AnalysisInput) -> str:
    # Receives AnalysisInput, generates findings by focus type
    # Severity guidelines: critical (>10% or >50 txns), high (5-10% or 20-50), medium (1-5% or 5-20), low (<1% or <5)
```

### insights.py

```python
async def get_summary(partner: str, date: str, llm_provider: LLMProvider) -> dict:
    # Query MongoDB → MetricsService → GroupingEngine → build AnalysisInput → LLM → return

async def get_discrepancies(partner: str, date: str, focus: str, llm_provider: LLMProvider) -> list[AnalysisResult]:
    # Query → MetricsService → GroupingEngine → generate_insights()

async def generate_insights(analysis_input: AnalysisInput, llm_provider: LLMProvider) -> list[AnalysisResult]:
    # Rule-based pre-process by focus + LLM enrich
    # Fallback: rule-based only if LLM fails
```

### services.py

```python
def build_analysis_input(partner, date, focus, metrics_result, grouped_results) -> AnalysisInput:
    # Build standardized input contract for LLM

def parse_llm_insights(llm_response: str) -> list[AnalysisResult]:
    # Parse JSON response from LLM, handle parse error → fallback

def format_findings(analysis_results: list[AnalysisResult]) -> list[str]:
    # Format AnalysisResult list to short string findings
```

### reporter.py

```python
class DailyReporter:
    def __init__(self, collection, llm_provider: LLMProvider, config: AnalysisConfig = None) -> None

    async def generate_report(self, date: str) -> dict:
        # Query partners active → call insights.get_summary() for each → aggregate

    def save_report(self, date: str) -> str:
        # Save JSON to ./reports/daily/{date}.json
```

### alerter.py

```python
class ThresholdAlerter:
    def __init__(self, config: AnalysisConfig = None) -> None

    def check_thresholds(self, summary_result: SummaryResult) -> list[Alert]:
        # Check mismatch rate and missing count thresholds from config
        # Severity scaling based on how far over threshold

    def alerts_for_report(self, report: dict) -> list[Alert]:
        # Run check for all partners in report
```

---

## src/api/

### __init__.py

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # MongoDB connection lifecycle management
    yield

def create_app() -> FastAPI:
    # Initialize FastAPI app with lifespan, include routers
```

### insights.py

```python
router = APIRouter(prefix="/api/v1")

@router.get("/insights/summary")
async def insights_summary(partner: str, date: str):
    # Validation: partner required, date format YYYY-MM-DD
    # Calls insights.get_summary()

@router.get("/insights/discrepancies")
async def insights_discrepancies(partner: str, date: str, focus: str = "operational"):
    # Validation: focus must be operational|partner|inconsistency
    # Calls insights.get_discrepancies()

@router.get("/reports/daily")
async def reports_daily(date: str):
    # Calls DailyReporter.generate_report()
```

---

## src/reconciliation/

### engine.py

```python
class ReconciliationEngine:
    def __init__(self, db: AsyncIOMotorDatabase) -> None
        # Initializes DataContainerRepo, InternalTransactionRepo, ReconciliationResultRepo

    def _normalize_status(self, status_str: str) -> TransactionStatus
        # Maps Vietnamese/English status strings to standard TransactionStatus

    def _resolve_partner_txn_id(self, partner_record: DataContainer) -> Optional[str]
        # Extracts reconciliation key: trace → vspTransId → id

    async def reconcile(self, partner: str, reconciliation_date: datetime) -> list[ReconciliationResult]
        # Full reconciliation: fetch → match → classify → store → return
```

**Key design:**
- Deterministic — same input always produces same output
- Idempotent write — delete-many + insert-many for matching keys
- Duplicate handling — latest `updatedAt` wins for same `partnerTxnId`
- Status normalization supports Vietnamese (Thành công, Thất bại, Hoàn tiền)
- Reconciliation key resolution follows priority chain: `trace` → `vspTransId` → `id`

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
