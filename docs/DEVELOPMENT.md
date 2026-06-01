# Development Guide

## Setup

### Prerequisites

- Python 3.14+
- `uv` package manager
- MongoDB (local or remote)

### Install Dependencies

```bash
uv sync --all-extras
```

### Environment

```bash
cp .env.example .env
# Edit .env with your MongoDB URL
```

## Running Tests

```bash
# All tests
uv run python -m pytest -v

# Specific module
uv run python -m pytest tests/test_normalizer.py -v

# With coverage
uv run python -m pytest --cov=src --cov-report=html

# Quick run (no coverage)
uv run python -m pytest -x -q
```

### Test Structure

| File | Tests | Coverage |
|------|-------|----------|
| `test_core_types.py` | 42 | Enums, types, constants, float rejection |
| `test_settings.py` | 7 | Settings defaults, env overrides |
| `test_config_cache.py` | 13 | TTL cache, expiration, thread safety |
| `test_config_validator.py` | 23 | Config validation, required coverage |
| `test_config_loader.py` | 17 | Cache integration, version resolution |
| `test_excel_reader.py` | 37 | Sheet selection, row filtering, patterns |
| `test_csv_reader.py` | 22 | CSV parsing, separation, quoting |
| `test_normalizer.py` | 57 | All conversion types, build_canonical |
| `test_validator.py` | 42 | Core validation, duplicate detection |
| `test_models.py` | 21 | Model creation, serialization |
| `test_indexes.py` | 11 | Index definitions, apply_indexes |
| `test_ingestion_pipeline.py` | 16 | Full pipeline, batch insertion, logging |
| `test_ingestion_integration.py` | 11 | End-to-end ingestion with real flows |
| `test_logger.py` | 22 | JSON/text formatting, event emission |
| `test_phase8.py` | 51 | Pre-reconciliation phase extensions |
| `test_reconciliation.py` | 6 | Matching, classification, duplicate handling |

**Total: 398 tests**

## Coding Conventions

### Type Hints

All functions must have type hints. Use `Optional[T]` for nullable types.

```python
def find_one(self, query: dict) -> Optional[T]:
```

### Pydantic Models

- Use `populate_by_name=True` for MongoDB alias support
- Use `arbitrary_types_allowed=True` for UUID, datetime
- Use `Field(alias="camelCase")` for MongoDB field names
- Use `@field_validator` for custom validation (e.g., float rejection)

```python
class MyModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: UUID = Field(default_factory=uuid4, alias="_id")
    name: str = Field(alias="myName")
```

### Async/Await

- All MongoDB operations are async via motor
- Use `async def` for methods that call the database
- Use `await` for all async calls
- Run sync I/O (file reading) in thread pool via `loop.run_in_executor()`

### Error Handling

- Never raise exceptions in normalizer or validator — collect as `ValidationError`
- Pipeline catches exceptions at top level, returns partial results
- Use `try/except` with best-effort for status updates on failure

### Testing

- TDD approach: write failing tests first, then implement
- Use `MagicMock` and `AsyncMock` for repository mocking
- Use `tmp_path` fixture for temporary files
- Mark async tests with `@pytest.mark.asyncio`

```python
@pytest.mark.asyncio
async def test_something(self, tmp_path):
    mock_repo = MagicMock(spec=SomeRepository)
    mock_repo.find_one = AsyncMock(return_value=None)
```

## Project Structure

```
AdapterService/
├── src/
│   ├── core/              # Canonical types, enums, constants
│   ├── config/            # Settings, cache, validator, loader
│   ├── readers/           # ExcelStreamReader, CSV reader
│   ├── normalizer/        # TransactionNormalizer
│   ├── validators/        # Validator
│   ├── pipeline/          # IngestionPipeline
│   ├── reconciliation/    # ReconciliationEngine (match + classify)
│   ├── scheduler/         # APScheduler daemon for automated fetching
│   ├── fetchers/          # SFTP, filedrop, API fetchers
│   ├── logging/           # StructuredLogger
│   └── models/            # MongoDB models, repositories, indexes
├── tests/                 # Test suite (398 tests)
├── docs/                  # Documentation
├── docker/                # Docker Compose services
├── pyproject.toml         # Project metadata, dependencies
├── requirements.txt       # Pip-installable dependencies
├── .env.example           # Environment variable template
└── requirement.md         # Original requirements document
```

## Git Workflow

```bash
# Create feature branch
git checkout -b feature/your-feature

# Make changes, commit
git add .
git commit -m "feat: your feature description"

# Push
git push origin feature/your-feature

# Merge to main (after review)
git checkout main
git merge feature/your-feature
git push origin main
```

## Adding a New Module

1. Create module directory under `src/`
2. Create `__init__.py` with exports
3. Write tests in `tests/`
4. Run `uv run python -m pytest` to verify
5. Update `docs/MODULES.md` with API reference

## Debugging

### Enable Debug Logging

```bash
APP_LOG_LEVEL=DEBUG uv run python your_script.py
```

### Inspect Normalization

```python
from src.normalizer.normalizer import TransactionNormalizer
from src.core.types import FieldMapping, FieldMappingType

normalizer = TransactionNormalizer([
    FieldMapping(path="id", column=1, type=FieldMappingType.STRING),
])
result = normalizer.normalize(("123",), row_number=1)
print(result.data)    # {"id": "123"}
print(result.errors)  # []
```

### Check Config Loading

```python
from src.config.loader import ConfigLoader
from src.config.cache import ConfigCache
from src.config.validator import ConfigValidator
from src.models.mapping_config import MappingConfigRepository
from src.core.enums import FileType

# Setup
repo = MappingConfigRepository(db)
cache = ConfigCache()
validator = ConfigValidator()
loader = ConfigLoader(repo, cache, validator)

# Load
config = await loader.load_by_partner_type("MOMO", "UPC", FileType.SETTLEMENT)
print(config.field_mappings)
```
