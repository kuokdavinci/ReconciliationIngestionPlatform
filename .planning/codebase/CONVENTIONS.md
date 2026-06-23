# Coding Conventions

**Analysis Date:** 2026-06-23

## Naming Patterns

**Python Files:**
- `snake_case` for all Python files: `ingestion_pipeline.py`, `mapping_contract.py`, `error_formatting.py`
- Classes use `PascalCase`: `IngestionPipeline`, `MappingContractValidation`, `CanonicalTransaction`
- Functions and methods use `snake_case`: `process_file()`, `validate_mapping_contract()`, `emit_file_started()`
- Private methods prefixed with `_`: `_compute_file_hash()`, `_flush_batch()`, `_validate_date()`
- Constants in `UPPER_SNAKE_CASE`: `MAX_FILE_SIZE_MB`, `DEFAULT_CURRENCY`, `FILE_HASH_KEY`

**TypeScript Files:**
- kebab-case for files: `review-center.ts`, `mapping-studio.ts`, `review-summary-drawer.tsx`
- React component files match component name in PascalCase: `button.tsx`, `toast.tsx`
- Hooks files prefixed with `use-`: `use-guided-review.ts`, `use-post-approval-polling.ts`
- State store files: `reconciliation-store.ts`
- Type definition files mirror domain name: `reconciliation.ts`, `review-center.ts`, `mapping.ts`

**TypeScript Code:**
- Functions use `camelCase`: `getCurrentActor()`, `showToast()`, `handleSaveMapping()`
- Components use `PascalCase`: `Button`, `ToastProvider`, `AppShell`, `EvidenceTable`
- Types and interfaces use `PascalCase`: `ReviewPacket`, `InsightItem`, `ReconciliationPageState`
- Constants in `UPPER_SNAKE_CASE`: `ACTOR_STORAGE_KEY`, `DEFAULT_ACTOR`, `BASE_URL`, `PARTNER`

**Python/TypeScript boundary:**
- Python API responses use `snake_case` internally, `camelize()` function in `src/api/response_utils.py` converts to camelCase for the frontend
- `to_camel()` function in `src/api/response_utils.py` handles the conversion dynamically
- TypeScript types receive camelCase keys from API: `partnerTxnId`, `reconciliationStatus`, `fieldMappings`

## Code Style

**Python Formatting:**
- Ruff configured in `pyproject.toml`: line-length=100, target-version="py311"
- Lint ignores: E402 (module import), E701 (compound statement), F841 (unused variable), F821 (undefined name), F401 (unused import)
- No explicit formatter config beyond ruff defaults; no black config detected

**TypeScript Formatting:**
- Prettier configured in `frontend-next/.prettierrc`: semi=true, singleQuote=true, tabWidth=2, trailingComma="es5"
- ESLint in `frontend-next/eslint.config.mjs`: uses `eslint-config-next/core-web-vitals` + `eslint-config-next/typescript` + `eslint-config-prettier`

**TypeScript tsconfig:**
- `frontend-next/tsconfig.json`: target="ES2017", strict=true, moduleResolution="bundler", JSX="react-jsx"
- Path alias `@/*` maps to `./src/*` — all imports use this: `import { Button } from "@/components/ui/button"`

## Import Organization

**Python imports in `src/`:**
1. Standard library first: `import logging`, `from datetime import datetime`, `from typing import Optional`
2. Third-party libraries: `from fastapi import APIRouter`, `from pydantic import BaseModel`
3. Local application imports: `from src.api.response_utils import camelize`, `from src.core.enums import FileType`

Example from `src/api/insights.py`:
```python
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from motor.motor_asyncio import AsyncIOMotorCollection

from src.api.response_utils import camelize
from src.analysis.config import AnalysisConfig
```

**TypeScript imports in `frontend-next/src/`:**
1. React/hooks first: `import { useCallback, useEffect, useMemo, useState } from "react"`
2. Library utilities: `import { get, post } from "./client"` or `import { redirect } from "next/navigation"`
3. Local types: `import type { ReviewPacket } from "@/types/review-center"`
4. Components: `import { Button } from "@/components/ui/button"`
5. Styles last: `import styles from "./review-center.module.css"`
6. Barrel imports from `@/lib/api/*`: `import * as api from "@/lib/api/reconciliation"`

## Error Handling

**Python API Layer:**
- Validation errors raise `HTTPException(status_code=400, detail=...)` with user-friendly messages
- Database unavailability raises `HTTPException(status_code=503, detail="...")`
- Business logic errors caught generically: `except Exception as exc:` then logged and re-raised as `HTTPException(500)`
- `HTTPException` from validation is re-raised directly (`raise`), not wrapped

Pattern from `src/api/insights.py`:
```python
try:
    partner = _validate_partner(partner)
    date = _validate_date(date)
except HTTPException:
    raise

try:
    result = await get_summary(...)
    return camelize(result)
except HTTPException:
    raise
except Exception as exc:
    logger.error(f"Error generating summary insights: {exc}", exc_info=True)
    raise HTTPException(status_code=500, detail=f"Failed to generate summary insights: {str(exc)}")
```

**Python Pipeline Layer:**
- Per-row errors collected (not thrown) — pipeline continues processing remaining rows
- Exception at pipeline level catches all, sets record status to FAILED, returns partial stats
- Broad `except Exception` with `pass` for best-effort cleanup in `src/pipeline/ingestion_pipeline.py` line 488-489

**TypeScript Frontend:**
- API client in `src/lib/api/client.ts` throws `Error(detail)` from `handleResponse()` when response is not ok
- Components use try/catch in async handlers with `showToast` for user feedback
- Custom hooks return error state strings: `setScopeError("")` / `setScopeError(err.message || "...")`

Pattern from `src/components/review-center/use-guided-review.ts`:
```typescript
try {
  const res = await api.classifyScope(localPacket._id);
  setScopeClassification(res);
} catch (err: any) {
  setScopeError(err.message || "Failed to load scope classification.");
} finally {
  setScopeLoading(false);
}
```

## Logging

**Python Structured Logger:**
- Custom `StructuredLogger` class in `src/logging/logger.py`
- JSON output by default (configurable to text via `APP_LOG_FORMAT` env)
- Typed emit methods: `emit_file_started()`, `emit_file_completed()`, `emit_file_failed()`, `emit_row_success()`, `emit_row_failed()`
- Module-level singleton via `get_structured_logger()` with double-checked locking
- Field truncation at 256 chars for safety (`_MAX_FIELD_LENGTH`)
- JSON formatter includes: timestamp, level, event, message, all extra fields
- Internal logging fields filtered out via `_INTERNAL_FIELDS` frozenset

**TypeScript Frontend:**
- No dedicated logging framework — uses `console.error` in API layer only
- User-facing errors surface via `ToastProvider` context with `showToast(message, variant)`

## Type Hints and Patterns

**Python Pydantic Patterns:**
- All data contracts use `pydantic.BaseModel` in `src/core/types.py` and `src/analysis/schemas.py`
- Enums use `StrEnum` from `enum` module: `FileType`, `ProcessingStatus`, `TransactionStatus`
- Field validators via `@field_validator`: `CanonicalTransaction.reject_float()` rejects float for monetary amounts
- Pydantic v2 style with `model_dump()` and `field_validator` (not deprecated `@validator`)
- Settings use `pydantic_settings.BaseSettings` with `SettingsConfigDict` for env prefix `APP_`
- Dataclasses for simple internal types: `@dataclass` in `src/services/mapping_contract.py`

**TypeScript Type Patterns:**
- Interfaces for all data shapes: `ReviewPacket`, `InsightItem`, `ReconciliationPageState`
- Explicit type imports with `type` keyword: `import type { ReviewPacket } from "@/types/review-center"`
- Type exports used in store: `export type ReconciliationStore = ReturnType<typeof useReconciliationStore>`
- Discriminated unions for variants: `type ToastVariant = "success" | "error" | "info"`
- `Record<string, unknown>` for dynamic/loose objects: `params: Record<string, unknown>`
- Optional fields marked with `?`: `completedAt?: string`

## Module Design

**Python Modules:**
- Each module has a docstring describing its purpose: `"""Reconciliation Engine for transaction content matching."""`
- Exports documented explicitly in module docstring
- Internal helpers prefixed with `_` underscore
- Lazy imports inside functions to avoid circular dependencies (seen in `src/api/__init__.py` and `src/api/insights.py`)

**TypeScript Modules:**
- Named exports always used (no default exports except Next.js page/layout components)
- API modules use barrel pattern: `import * as api from "@/lib/api/reconciliation"`
- Hooks return objects with named properties for destructuring
- Context providers wrap children with `.Provider` pattern

## Function Design

**Python:**
- Functions include docstrings with Args/Returns/Raises sections (Google-style)
- Type hints on all parameters and return types
- Default parameter values where sensible: `batch_size: int = 100`

**TypeScript:**
- Arrow functions for callbacks and event handlers: `const handleClose = useCallback(() => {...}, [])`
- Props interface defined above component, destructured with defaults
- Optional callback props with `() => void` type

## Comments

**Python:**
- Module-level docstrings describe purpose, exports, flow
- Section dividers: `# ---- Section Title ----` 
- Inline comments for steps: `# Step 1: Compute file hash`
- Google-style docstrings with Args/Returns/Raises sections
- Architecture notes as comments: `# (DATA-FLOW-01)`

**TypeScript:**
- Minimal inline comments
- ESLint disable comments used: `/* eslint-disable @typescript-eslint/no-explicit-any */`
- No JSDoc/TSDoc convention detected

---

*Convention analysis: 2026-06-23*
