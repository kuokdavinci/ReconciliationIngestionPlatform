# Architecture Debt Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mypy a real check for the current source tree and remove the duplicated normalization loop before the canonical ingestion-record migration.

**Architecture:** Keep the existing public normalizer API, but route `normalize()` and `normalize_with_trace()` through one field-evaluation loop with optional trace collection. Remove the module-level mypy `ignore_errors` override and fix the revealed errors at their actual type boundaries using existing Pydantic aliases, explicit guards, and narrow casts only where dynamic repository/API data requires them.

**Tech Stack:** Python 3.11, pytest, mypy, Ruff, Pydantic 2, FastAPI, existing repository interfaces.

**Spec:** `.superpowers/sdd/2026-08-27-ingestion-canonical-record-design.md` (debt cleanup is a prerequisite; canonical record implementation remains a later change).

## Global Constraints

- Preserve normalization, validation, quarantine, persistence, and API runtime behavior.
- Keep `ignore_missing_imports = true`; do not reintroduce `ignore_errors = true`.
- Do not add third-party dependencies or broad `# type: ignore` comments.
- Keep the public signatures of `TransactionNormalizer.normalize()` and `normalize_with_trace()` unchanged.
- Do not change `build_fast_dict()`/`build_canonical()` yet; the approved canonical-record work will remove that temporary duplication.
- Work only on `workstream-e`; do not stage unrelated user changes if they appear.

---

### Task 1: Characterize the normalizer contract and close the direct mapping hole

**Files:**
- Modify: `tests/test_normalizer.py`
- Modify: `src/normalizer/normalizer.py`

**Interfaces:**
- Consumes: existing `FieldMapping`, `NormalizationResult`, and `FieldNormalizationTrace` contracts.
- Produces: a regression test proving direct mapping conversion with `mapping=None` returns a quality violation instead of raising `TypeError`.

- [ ] **Step 1: Write the failing test**

Add this test beside the existing `_convert_mapping` tests:

```python
def test_mapping_without_configuration_returns_quality_violation(self):
    mapping = FieldMapping(
        path="status",
        column="A",
        type=FieldMappingType.MAPPING,
        mapping=None,
    )

    value, error = TransactionNormalizer._convert_mapping("SUCCESS", mapping)

    assert value is None
    assert error is not None
    assert error.code == QualityRuleCode.MALFORMED_ROW
    assert error.field == "status"
```

- [ ] **Step 2: Run the focused test to verify RED**

Run: `.venv/bin/pytest tests/test_normalizer.py -q -k mapping_without_configuration`

Expected: FAIL with a `TypeError` at `str_value in fm.mapping`, proving the optional mapping contract is not safe for direct callers.

- [ ] **Step 3: Implement the minimal guard**

At the start of `TransactionNormalizer._convert_mapping()`, bind the optional mapping and reject it before membership/index operations:

```python
mapping = fm.mapping
if mapping is None:
    return None, _normalization_violation(
        code=QualityRuleCode.MALFORMED_ROW,
        field=fm.path,
        message=f"mapping dict not configured for {fm.path}",
        row=row_number,
    )
```

Use `mapping` for the remaining lookups:

```python
if str_value in mapping:
    return mapping[str_value], None
if "others" in mapping:
    return mapping["others"], None
```

- [ ] **Step 4: Run the focused test to verify GREEN**

Run: `.venv/bin/pytest tests/test_normalizer.py -q -k mapping_without_configuration`

Expected: PASS.

- [ ] **Step 5: Commit the behavior fix**

```bash
git add tests/test_normalizer.py src/normalizer/normalizer.py
git commit -m "fix: guard unconfigured normalizer mappings"
```

### Task 2: Collapse `normalize()` and `normalize_with_trace()` into one loop

**Files:**
- Modify: `src/normalizer/normalizer.py:97-247`
- Modify: `tests/test_normalizer.py`

**Interfaces:**
- Consumes: the public `normalize(row, row_number)` and `normalize_with_trace(row, row_number)` methods.
- Produces: one private implementation with signature `_normalize(row: Any, row_number: int | None, collect_trace: bool) -> tuple[NormalizationResult, list[FieldNormalizationTrace]]`.

- [ ] **Step 1: Write the parity characterization test**

Add a test using a valid constant, string, decimal, date, and mapping plus a missing source field. Assert the result from both public methods has identical `data` and error fields, while the trace API returns one trace per mapping and carries the field error:

```python
def test_normalize_and_trace_preserve_the_same_field_results(self):
    mappings = [
        FieldMapping(path="id", column="A", type=FieldMappingType.STRING),
        FieldMapping(path="amount", column="B", type=FieldMappingType.DECIMAL),
        FieldMapping(path="currency", type=FieldMappingType.CONSTANT, constant="VND"),
        FieldMapping(
            path="status",
            column="C",
            type=FieldMappingType.MAPPING,
            mapping={"ok": "SUCCESS"},
        ),
        FieldMapping(path="transDate", column="D", type=FieldMappingType.DATE),
        FieldMapping(path="trace", column="E", type=FieldMappingType.STRING),
    ]
    row = {"A": "TX-1", "B": "100", "C": "ok", "D": "2025-01-01T00:00:00Z"}
    normalizer = TransactionNormalizer(mappings)

    plain = normalizer.normalize(row, row_number=7)
    traced, traces = normalizer.normalize_with_trace(row, row_number=7)

    assert traced.data == plain.data
    assert [error.model_dump() for error in traced.errors] == [
        error.model_dump() for error in plain.errors
    ]
    assert len(traces) == len(mappings)
    assert traces[-1].path == "trace"
    assert traces[-1].error is not None
```

- [ ] **Step 2: Run the characterization test before the refactor**

Run: `.venv/bin/pytest tests/test_normalizer.py -q -k preserve_the_same_field_results`

Expected: PASS against the current implementation. This is an intentional characterization test: the observable contract already exists, and the refactor must preserve it.

- [ ] **Step 3: Replace the duplicated public loops with one implementation**

Make the public methods thin wrappers:

```python
def normalize(self, row: Any, row_number: int | None = None) -> NormalizationResult:
    result, _ = self._normalize(row, row_number, collect_trace=False)
    return result

def normalize_with_trace(
    self, row: Any, row_number: int | None = None
) -> tuple[NormalizationResult, list[FieldNormalizationTrace]]:
    return self._normalize(row, row_number, collect_trace=True)
```

Move the current trace loop into `_normalize()`. Use one `source_value`/`error` flow for both modes: a `QualityViolation` returned by `_resolve_source()` becomes `error`, a `None` source creates the existing missing-value violation, conversion dispatch remains unchanged, and the result list is updated once. Append `FieldNormalizationTrace` only when `collect_trace` is true. Do not call normalization twice and do not add a new strategy/factory class.

- [ ] **Step 4: Run focused normalizer tests**

Run: `.venv/bin/pytest tests/test_normalizer.py tests/test_timestamp_normalization.py -q`

Expected: all focused tests pass with no changed error codes or output data.

- [ ] **Step 5: Commit the deduplication**

```bash
git add tests/test_normalizer.py src/normalizer/normalizer.py
git commit -m "refactor: share normalizer field evaluation"
```

### Task 3: Make mypy report the full source tree

**Files:**
- Modify: `pyproject.toml:63-81`

**Interfaces:**
- Consumes: the existing CI command `uv run mypy src/ --show-error-codes`.
- Produces: a configuration that checks every local `src` module while still tolerating missing third-party stubs.

- [ ] **Step 1: Remove the module-wide error suppression**

Delete the entire `[[tool.mypy.overrides]]` block and keep only:

```toml
[tool.mypy]
ignore_missing_imports = true
explicit_package_bases = true
```

- [ ] **Step 2: Run mypy to verify RED and capture the real debt**

Run: `.venv/bin/mypy src/ --show-error-codes`

Expected: failure showing the currently hidden errors, including the known errors in `config/signature.py`, readers, normalizer, pipeline, API, and analysis. Do not add an override to make this command green.

- [ ] **Step 3: Confirm only the intended configuration changed**

Run: `git diff -- pyproject.toml`

Expected: only the `tool.mypy` override removal is present before source fixes.

### Task 4: Fix foundational config, reader, and normalizer typing errors

**Files:**
- Modify: `src/config/signature.py`
- Modify: `src/readers/json_reader.py`
- Modify: `src/readers/csv_reader.py`
- Modify: `src/readers/excel_reader.py`
- Modify: `src/normalizer/normalizer.py`

**Interfaces:**
- Consumes: current file readers, `StructureSignature`, and normalizer contracts.
- Produces: correctly narrowed values without behavior changes.

- [ ] **Step 1: Add the minimal annotations and return types**

Use `list[list[str]]` for the local `rows` variables in `_read_raw_csv()` and `_read_raw_xlsx()`. In `structure_signature_shape()`, keep the values as `Any` until the existing `isinstance` checks and only return a tuple after confirming `headers` is a non-empty list and `column_count` is an `int` or replacing it with `len(headers)`.

Import `Literal` from `typing` and change all three reader `__exit__` annotations to `Literal[False]`; their behavior already always returns `False`.

In `_convert_mapping()`, use the `mapping` local guard from Task 1 so mypy can prove membership and indexing are safe.

- [ ] **Step 2: Run the targeted type check**

Run: `.venv/bin/mypy src/config/signature.py src/readers/ src/normalizer/ --show-error-codes`

Expected: no errors in these paths.

- [ ] **Step 3: Run the affected tests**

Run: `.venv/bin/pytest tests/test_normalizer.py tests/test_timestamp_normalization.py tests/test_json_reader.py tests/test_csv_reader.py tests/test_excel_reader.py tests/test_config_signature.py -q`

Expected: PASS. If a named test file is absent, run the existing reader/signature test files discovered with `rg --files tests | rg 'reader|signature'` and record that exact command in the task report.

- [ ] **Step 4: Commit the foundational typing fixes**

```bash
git add pyproject.toml src/config/signature.py src/readers src/normalizer
git commit -m "type: enable checks for config readers and normalizer"
```

### Task 5: Fix pipeline/domain typing at Pydantic and repository boundaries

**Files:**
- Modify: `src/pipeline/file_claim.py`
- Modify: `src/pipeline/row_processor.py`
- Modify: `src/pipeline/row_batch_coordinator.py`
- Modify: `src/pipeline/ingestion_pipeline.py`

**Interfaces:**
- Consumes: existing Pydantic models, repository ports, and pipeline dependency composition.
- Produces: typed pipeline construction with the same runtime objects and dependency selection.

- [ ] **Step 1: Fix model constructor keyword errors using declared aliases**

For `ReconciliationFile`, `DataContainer`, and `IngestionQuarantineRecord`, use the exact Pydantic field aliases reported by mypy (`fileName`, `fileHash`, `fileType`, `reconciliationDate`, `processingStatus`, `configVersion`, `fetchUnitKey`, `fetchUnitMetadata`, `sourceFilePath`, `scopeType`, `scopeConfidence`, `scopeReason`, `scopeSignals`; `workflowType`, `sourceFileId`, `ingestionKey`, `partnerData`; and the quarantine camelCase equivalents). Do not add `type: ignore` or change model aliases.

- [ ] **Step 2: Narrow the row processor transaction union**

Declare the post-builder variable as `CanonicalTransaction | dict[str, Any] | None`, keep the existing `isinstance(txn, dict)` branch for trace/key access, and construct `DataContainer` with aliases or `model_validate` so the type checker sees the actual Pydantic contract. Preserve the current fast/normal behavior until the later canonical-record task.

- [ ] **Step 3: Narrow optional repositories once at composition boundaries**

In `ingestion_pipeline.py`, replace repeated `Optional` repository use with explicit checks immediately after dependency resolution. Raise the existing initialization error when a required repository is absent, then use the narrowed local variables. For the heterogeneous list around repository health checks, use separate typed lists per repository interface rather than one inferred list that changes element type.

- [ ] **Step 4: Run pipeline type checks and unit tests**

Run: `.venv/bin/mypy src/pipeline/ --show-error-codes`

Expected: no pipeline errors.

Run: `.venv/bin/pytest tests/test_ingestion_components.py tests/test_ingestion_pipeline.py tests/test_quarantine_adapters.py -q`

Expected: PASS with existing accounting, quarantine, and persistence behavior.

- [ ] **Step 5: Commit the pipeline typing fixes**

```bash
git add src/pipeline
git commit -m "type: tighten ingestion pipeline boundaries"
```

### Task 6: Fix API and analysis typing without weakening the gate

**Files:**
- Modify: `src/api/operations.py`
- Modify: `src/api/data_explorer.py`
- Modify: `src/api/reconciliation.py`
- Modify: `src/api/mappings.py`
- Modify: `src/api/copilot.py`
- Modify: `src/api/__init__.py`
- Modify: `src/api/insights.py`
- Modify: `src/analysis/insights.py`

**Interfaces:**
- Consumes: FastAPI request validation, repository return values, analysis provider interfaces, and serialized API responses.
- Produces: explicit request guards and typed dynamic data at the API/analysis boundaries; no endpoint behavior changes.

- [ ] **Step 1: Reuse existing validation helpers for optional query values**

After `_validate_partner()` and `_validate_date()` calls, assign their narrowed `str` results to new local names or annotate the helper return type as `str`. Pass those narrowed values to repositories and command objects. Keep the existing HTTP 400 behavior for missing/invalid values.

- [ ] **Step 2: Use Pydantic aliases for API payload construction**

Update `src/api/copilot.py` constructors to use `reviewedBy` as declared by `ReviewDecisionPayload` and `MappingReviewPayload`, preserving the incoming JSON/API aliases. In `src/api/mappings.py`, type the output accumulator as `dict[str, Any]` and normalize optional path values after the existing validation check before using `/`.

- [ ] **Step 3: Type provider and analysis collection boundaries**

Use the existing `LLMProvider`/provider protocol expected by `get_summary()` and `get_discrepancies()` when creating the provider. Annotate dynamic Mongo/repository documents at the point they are read, guard `None` before `strftime`/iteration, and use typed local maps for status/amount data. Preserve the current output shape and duplicate status aggregation.

- [ ] **Step 4: Fix the remaining small module errors**

In `src/api/operations.py`, keep the repository/model variable types distinct instead of assigning a raw dict to a `ReconciliationFile`. In `src/api/__init__.py`, annotate the module client variable with its concrete client type or `Any` at the external SDK boundary. In `src/analysis/insights.py`, rename repeated local variables where mypy reports `no-redef` and narrow optional/dynamic values before enum conversion, `.items()`, `float()`, and iteration.

- [ ] **Step 5: Run API and analysis checks**

Run: `.venv/bin/mypy src/api/ src/analysis/ --show-error-codes`

Expected: no errors.

Run: `.venv/bin/pytest tests/test_api_*.py tests/test_analysis_*.py -q --ignore=tests/test_analysis_e2e.py`

Expected: PASS, with external LLM E2E still excluded as in CI.

- [ ] **Step 6: Commit the API/analysis typing fixes**

```bash
git add src/api src/analysis
git commit -m "type: close API and analysis type gaps"
```

### Task 7: Full verification and handoff

**Files:**
- Modify: documentation only if the verification result requires a factual update; otherwise no documentation change.

**Interfaces:**
- Consumes: the complete source tree and focused regression suites.
- Produces: evidence that the debt cleanup is complete and the branch is ready for canonical-record implementation.

- [ ] **Step 1: Run the full static checks**

Run:

```bash
.venv/bin/mypy src/ --show-error-codes
.venv/bin/ruff check src dags scripts
```

Expected: mypy reports `Success: no issues found` and Ruff exits 0.

- [ ] **Step 2: Run the focused regression suite**

Run:

```bash
.venv/bin/pytest tests/test_normalizer.py tests/test_timestamp_normalization.py tests/test_ingestion_components.py tests/test_ingestion_pipeline.py tests/test_quarantine_adapters.py tests/test_api_automation.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run the broader non-E2E suite**

Run: `.venv/bin/pytest tests/ --ignore=tests/test_analysis_e2e.py --ignore=tests/test_ingestion_integration.py --ignore=tests/test_ingestion_pipeline.py --ignore=tests/test_seed_momo_e2e.py --ignore=tests/test_sprint1_eval_benchmark.py -q`

Expected: pass with no new failures; integration/E2E exclusions match the repository CI boundary.

- [ ] **Step 4: Verify the diff and working tree**

Run: `git diff HEAD~5..HEAD --stat && git status --short`

Expected: only the planned debt-cleanup files are committed; any unrelated user changes are left untouched and reported separately.

- [ ] **Step 5: Commit any final documentation update only if needed**

If verification changes no facts, do not create a documentation commit. Report the exact static/test commands and results, then proceed to the separately approved canonical-record plan.
