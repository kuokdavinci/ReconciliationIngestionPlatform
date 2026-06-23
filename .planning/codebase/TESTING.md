# Testing Patterns

**Analysis Date:** 2026-06-23

## Test Framework

**Python Backend (Primary):**
- **Runner:** pytest >=7.0
- **Async support:** pytest-asyncio >=1.4.0
- **Coverage:** pytest-cov >=4.0
- **Config file:** `pyproject.toml` — `[tool.pytest.ini_options]`
- **Run Commands:**

```bash
uv run pytest tests/ -v                      # Run all tests (default)
uv run pytest tests/ -x --tb=short           # Fast: stop on first failure
uv run pytest tests/ -v --cov=src            # With coverage
uv run pytest tests/ -v --e2e                # Include E2E tests (requires real services)
uv run pytest tests/test_reconciliation.py -v -k "matched"  # Filter by test name
```

**TypeScript Frontend:**
- **Not detected.** No test framework is configured in `frontend-next/package.json`. No `jest.config.*` or `vitest.config.*` files exist. No `*.test.ts` or `*.spec.ts` files found in `frontend-next/src/`. Frontend testing is absent.

## pytest Configuration (`pyproject.toml`)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
asyncio_mode = "auto"
markers = [
    "e2e: mark test as end-to-end (requires real services)",
]
```

Key settings:
- `asyncio_mode = "auto"` — all test files automatically support async tests, no need for `@pytest.mark.asyncio` on every test (though it is used redundantly throughout)
- `--e2e` CLI flag gated in `conftest.py` via `pytest_addoption`
- E2E tests skipped by default, require `--e2e` flag

## Test File Organization

**Location:** All tests in flat `tests/` directory (no subdirectories for unit vs integration)

**Naming:**
- Files: `test_<module>.py` — mirrors the module under test: `test_reconciliation.py` tests `src/reconciliation/engine.py`
- Classes: `Test<Feature>` — groups related tests: `TestProcessFileHappyPath`, `TestReconciliationMatched`
- Functions: `test_<scenario>` — descriptive names: `test_process_file_all_rows_valid`, `test_reconciliation_amount_mismatch`

**Structure:**
```
tests/
├── conftest.py                     # Shared fixtures (mock_db, sample_mapping_config, test_excel_file, etc.)
├── __init__.py
├── test_api_*.py                   # API endpoint tests (fastapi TestClient)
├── test_analysis_*.py              # Analysis layer tests
├── test_config_*.py                # Config loader, cache, validator tests
├── test_core_types.py              # Core type tests
├── test_ingestion_pipeline.py      # Pipeline tests (most comprehensive)
├── test_ingestion_integration.py   # Integration tests with real file fixtures
├── test_logger.py                  # StructuredLogger tests
├── test_models.py                  # Model/repository tests
├── test_normalizer.py              # Normalizer tests
├── test_reconciliation.py          # Reconciliation engine tests
├── test_settings.py                # Settings/env tests
└── test_validator.py               # Validator tests
```

## Test Structure

**Class-based grouping:** Tests are organized into classes even when no shared setup is needed. This is the dominant pattern.

```python
class TestReconciliationMatched:
    """Tests for MATCHED reconciliation status."""

    @pytest.mark.asyncio
    async def test_reconciliation_matched(self, mock_db):
        """Test scenario where partner transaction matches internal transaction exactly."""
        engine = ReconciliationEngine(mock_db)
        # 1. Setup mock data
        recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)
        partner_record = DataContainer(...)
        internal_record = InternalTransaction(...)
        # 2. Mock repositories
        engine._data_repo.find_many = AsyncMock(return_value=[partner_record])
        engine._internal_repo.find_many = AsyncMock(return_value=[internal_record])
        engine._result_repo.collection.delete_many = AsyncMock()
        engine._result_repo.insert_many = AsyncMock(return_value=1)
        # 3. Run
        results = await engine.reconcile(partner, recon_date)
        # 4. Assert
        assert len(results) == 1
        assert results[0].reconciliation_status == ReconciliationStatus.MATCHED
```

**Pattern:**
- Docstring on class and method describing the scenario
- `@pytest.mark.asyncio` on every async test method (redundant with `asyncio_mode = "auto"`)
- Setup comments: `# 1. Setup mock data`, `# 2. Mock repositories`, `# 3. Run`, `# 4. Assert`
- Arrange-Act-Assert structure clearly separated

## Mocking

**Framework:** `unittest.mock` (standard library) — `AsyncMock`, `MagicMock`, `Mock`

**Patterns:**

```python
# AsyncMock for async methods
engine._data_repo.find_many = AsyncMock(return_value=[partner_record])

# MagicMock for objects (db, repos)
mock_db = MagicMock()
mock_db.__getitem__ = MagicMock(side_effect=lambda name: MagicMock())

# MagicMock with spec to enforce interface
mock_repo = MagicMock(spec=ReconciliationFileRepository)
mock_repo.find_by_file_hash = AsyncMock(return_value=None)
mock_repo.create = AsyncMock(side_effect=lambda doc: doc)

# Tracking call count and arguments
assert mock_data_repo.insert_many.call_count == 2
first_batch = mock_data_repo.insert_many.call_args_list[0][0][0]

# Await count for async mocks
assert engine._result_repo.insert_many.await_count == 3
```

**What to Mock:**
- Database client and collections — `mock_db` fixture returns a `MagicMock` where `db["collection_name"]` returns a mock collection
- Repository methods — each method (`find_many`, `insert_many`, `update_status`) is individually replaced with `AsyncMock`
- Config loaders — `MagicMock(spec=ConfigLoader)` with `AsyncMock` return values
- External services (SFTP, API fetchers)

**What NOT to Mock:**
- Pydantic models are constructed with real data: `MappingConfig(...)`, `DataContainer(...)` — fixtures create real model instances
- Enum values are used directly: `ProcessingStatus.COMPLETED`, `ReconciliationStatus.MATCHED`
- The engine/method under test is always real, never mocked

## Fixtures and Factories

**conftest.py (`tests/conftest.py`):**
- Shared fixtures used across test files

```python
@pytest.fixture
def mock_db() -> MagicMock:
    """AsyncMock for AsyncIOMotorDatabase with collection mocks."""
    db = MagicMock()
    def _mock_collection(name):
        coll = MagicMock()
        coll.count_documents = AsyncMock(return_value=0)
        return coll
    db.__getitem__ = MagicMock(side_effect=_mock_collection)
    return db

@pytest.fixture
def sample_mapping_config() -> MappingConfig:
    """MappingConfig with field mappings for realistic partner test data."""
    return MappingConfig(...)
```

**Key fixtures:**
- `mock_db` — returns `MagicMock` with auto-mocking collection access
- `mock_reconciliation_file_repo` — tracks `find_by_file_hash`, `create`, `update_one`
- `mock_data_container_repo` — tracks `insert_many` calls
- `sample_mapping_config` — real `MappingConfig` with 5 field mappings
- `mock_config_loader` — `MagicMock(spec=ConfigLoader)` with `AsyncMock` return values
- `test_excel_file` — creates temporary `.xlsx` with 10 rows (mixed valid/invalid), yields path, cleans up
- `empty_excel_file` — header-only .xlsx
- `all_invalid_excel_file` — all rows have empty IDs
- `large_excel_file` — 250 valid rows

**Helper factories (in test files):**
- `_make_config()` in `test_config_loader.py` — creates minimal `MappingConfig`
- `_make_mock_db()` in `test_ingestion_pipeline.py` — inline mock db factory
- `_create_test_app()` in `test_api_mappings.py` — creates FastAPI TestClient with mock db

## Coverage

**Requirements:** Not explicitly enforced — no `--cov` flag in CI or Makefile. `pytest-cov` is available as dev dependency but not configured with minimum thresholds.

**View Coverage:**
```bash
uv run pytest tests/ --cov=src --cov-report=term-missing
```

## Test Types

**Unit Tests (dominant):**
- Scope: Single class/method in isolation
- Approach: All dependencies mocked (repos, db, external services)
- Focus: Business logic correctness (reconciliation matching, normalization, validation)
- Examples: `test_reconciliation.py`, `test_normalizer.py`, `test_validator.py`

**Integration Tests:**
- Scope: Pipeline + file I/O + database interaction
- Approach: Real temporary files, mocked database layer
- Focus: Component wiring, batch insertion, error propagation
- Examples: `test_ingestion_integration.py`, `test_ingestion_pipeline.py`

**API Tests:**
- Scope: FastAPI endpoint behavior
- Approach: `TestClient` with mock `app.state.db`, `_AsyncCursor` for MongoDB cursor iteration
- Focus: Status codes, response shapes, error responses
- Examples: `test_api_mappings.py`, `test_api_insights.py`, `test_api_reconciliation.py`

**E2E Tests:**
- Scope: Full system with real LLM provider and MongoDB
- Mark: `@pytest.mark.e2e`
- Gated: Skipped unless `--e2e` flag passed
- Examples: `test_analysis_e2e.py`

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_reconciliation_matched(self, mock_db):
    engine = ReconciliationEngine(mock_db)
    # ... setup ...
    results = await engine.reconcile(partner, recon_date)
    assert len(results) == 1
```

**Error Testing:**
```python
def test_empty_partner_returns_400(self):
    """Returns 400 when partner parameter is empty string."""
    app, _ = _create_test_app()
    client = TestClient(app)
    response = client.get("/api/v1/mappings", params={"partner": ""})
    assert response.status_code == 400
    assert "cannot be empty" in response.json()["detail"]
```

**Custom Async Cursor for MongoDB Tests:**
```python
class _AsyncCursor:
    """Async iterator that yields documents, mimicking a MongoDB cursor."""
    def __init__(self, docs: list[dict]):
        self._docs = docs
        self._idx = 0
    def __aiter__(self):
        return self
    async def __anext__(self):
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        val = self._docs[self._idx]
        self._idx += 1
        return val
```

**Custom Mock Logger:**
```python
class MockStructuredLogger:
    """Mock logger that captures emitted events for test verification."""
    def __init__(self):
        self.events = []
    def emit_file_started(self, file_id, file_name, partner):
        self.events.append(("FILE_STARTED", {...}))
    # ... other emit methods ...
```

**Multiple Assert Verification:**
```python
# Verify batch call count
assert engine._result_repo.insert_many.await_count == 3
inserted_batch_sizes = [
    len(call.args[0]) for call in engine._result_repo.insert_many.await_args_list
]
assert inserted_batch_sizes == [2, 2, 1]
```

**Monkeypatch for Settings Override:**
```python
def test_mongodb_url_env_override(self, monkeypatch):
    import importlib
    monkeypatch.setenv("APP_MONGODB_URL", "mongodb://custom:27017/testdb")
    from src.config import settings as settings_module
    importlib.reload(settings_module)
    assert settings_module.settings.mongodb_url == "mongodb://custom:27017/testdb"
```

## CI Integration

**GitHub Actions:** `.github/workflows/backend-quality.yml`

```yaml
- name: Lint
  run: uv run ruff check src/api src/config src/models/audit_event.py ...

- name: Run test suite
  run: uv run pytest -v --tb=short
```

- Runs on push to `main` and `feature/*` branches
- Uses `astral-sh/setup-uv@v3` with caching
- Python version from `pyproject.toml` (`>=3.11`)
- Lints a subset of files with `ruff check`
- Runs full test suite excluding E2E tests (since `--e2e` is not passed)

## Known Gaps

1. **No frontend testing** — Zero tests exist for the TypeScript/Next.js frontend. No test runner configured in `frontend-next/package.json`.
2. **No contract/property-based testing** — No use of Hypothesis or similar tools.
3. **No snapshot testing** — No pytest-snapshot or similar for API response shapes.
4. **E2E tests are minimal** — Only one E2E test file (`test_analysis_e2e.py`) with limited coverage.
5. **Coverage thresholds not enforced** — No minimum coverage configuration in CI or pytest config.
6. **AsyncMock redundant marking** — `@pytest.mark.asyncio` is applied even though `asyncio_mode = "auto"` is set.

---

*Testing analysis: 2026-06-23*
