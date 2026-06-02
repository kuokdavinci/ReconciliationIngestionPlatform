# Phase 13: Backend Audit & UI Polish - Context

**Gathered:** 2026-06-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Audit all backend components (ingestion, normalization, validation, reconciliation, AI analysis) for correctness with edge case test coverage. Add a data flow guard in the reconciliation engine to skip and log unmapped records. Refine the UI with a new Mapping Configs dashboard tab (active configs per partner with field mapping details) and a reconciliation health widget on the Overview page.

</domain>

<decisions>
## Implementation Decisions

### Backend Audit Scope
- **D-01:** Audit ALL components: ingestion pipeline, TransactionNormalizer, Validator, ReconciliationEngine, and AI analysis layer
- **D-02:** Focus on edge case coverage — verify existing tests cover: empty files, missing required fields, duplicate traces, amount mismatches, status mapping gaps, unmapped partner status values

### Data Flow Guard
- **D-03:** Add explicit pre-check in ReconciliationEngine before processing partner records — verify each record has valid normalized data (non-empty partnerData, valid amount/status)
- **D-04:** Records failing the pre-check are skipped with a structured warning log entry (not rejected as errors — the file continues processing)
- **D-05:** Reconciliation stats summary includes unmapped/skipped record counts

### UI Mapping Dashboard
- **D-06:** New sidebar navigation tab "Mapping Configs" (between Reconciliation and AI Insights)
- **D-07:** Display active mapping configurations per partner with field mapping details (column, type, required flag, mapping rules)
- **D-08:** New API endpoint `GET /api/v1/mappings` to serve mapping config data from `reconciliation_mapping_config` collection
- **D-09:** UI shows config version, partner, file type, sheet name, start row, and list of field mappings

### UI Core Feature Widgets
- **D-10:** Add reconciliation health widget to Overview dashboard showing: healthy/anomaly status per partner, last reconciliation timestamp, pending items count
- **D-11:** Widget fetches data from existing `/api/v1/reconciliation/stats` endpoint

### OpenCode's Discretion
- Test framework choice (pytest — follow existing patterns in `tests/`)
- UI component styling (follow existing Material Symbols + CSS patterns)
- Reconciliation health widget visual design (inline in app.js, consistent with existing panels)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & State
- `.planning/ROADMAP.md` — Phase 13 requirements and goal
- `.planning/PROJECT.md` — Project architecture, core principles
- `.planning/STATE.md` — Current project state and decisions
- `.planning/phases/01-foundation/01-CONTEXT.md` — Foundation decisions (Python, MongoDB, Motor, FastAPI)

### Source Code (read before modifying)
- `src/reconciliation/engine.py` — ReconciliationEngine to add unmapped data guard
- `src/normalizer/normalizer.py` — TransactionNormalizer (existing unmapped value handling)
- `src/api/reconciliation.py` — Existing reconciliation API endpoints (pattern for new mapping endpoint)
- `src/api/data_explorer.py` — Data explorer API endpoints (reference for pagination, filtering)
- `web/app.js` — Main UI application (add new tabs, widgets here)
- `web/index.html` — UI shell (sidebar navigation)
- `web/styles.css` — UI styles
- `src/models/reconciliation_mapping_config.py` — Mapping config model (if exists)

### Tests
- `tests/test_api_reconciliation.py` — Existing reconciliation API tests
- `tests/test_api_data_explorer.py` — Existing data explorer API tests
- `tests/test_reconciliation.py` — Existing reconciliation engine tests
- `tests/test_normalizer.py` — Existing normalizer tests
- `tests/conftest.py` — Test fixtures and patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/models/reconciliation_mapping_config.py` — Mapping config model (if exists, reuse for new endpoint)
- Existing API patterns in `src/api/reconciliation.py` and `src/api/data_explorer.py` — APIRouter, repository pattern, validation helpers
- Web UI has `renderOverview()`, `renderSettings()` — follow existing rendering patterns for new Mapping Configs tab
- Existing sidebar navigation in `web/app.js` routes array — add new route entry

### Established Patterns
- FastAPI: APIRouter with `/api/v1/` prefix, dependency injection via `request.app.state.db`
- Tests: pytest async, conftest fixtures with test MongoDB, `httpx.AsyncClient` for API tests
- UI: Vanilla JS SPA with hash-based routing, fetchJson wrapper, Material Symbols icons
- Data serialization: `model_dump(by_alias=True)`, Decimal → string conversion

### Integration Points
- New mapping endpoint: `src/api/` directory, register in existing `src/api/__init__.py`
- New UI tab: add to `routes` array in `web/app.js`, render function `renderMappings()`
- Reconciliation health widget: add to `renderOverview()` in `web/app.js`

</code_context>

<specifics>
## Specific Ideas

- Backend audit should reuse existing test infrastructure — add edge case test cases to existing test files rather than creating new ones
- The mapping configs tab should show hierarchical data: Partner → Config Version → Field Mappings list
- The reconciliation health widget should use the status badge colors already defined in CSS

</specifics>

<deferred>
## Deferred Ideas

AI-powered mapping config suggestion from partner data — noted from user's earlier description. Belongs in a future phase focused on AI integration for mapping.

</deferred>

---

*Phase: 13-backend-audit-ui-polish*
*Context gathered: 2026-06-02*
