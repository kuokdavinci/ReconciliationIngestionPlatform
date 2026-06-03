# Phase 15: UI/UX Polish & Data Explorer Enhancement — Context

**Gathered:** 2026-06-02
**Status:** Ready for planning
**Source:** User feedback — review of current MVP UI

<domain>
## Phase Boundary

Fix visual inconsistencies, improve layout hierarchy, enhance Data Explorer querying, and remove non-functional UI elements in the dashboard application. All changes are frontend-only (web/app.js, web/styles.css) and backend API extension for new filter parameters in Data Explorer endpoints (src/api/data_explorer.py). No new collections, no new routes, no AI layer changes.

</domain>

<decisions>
## Implementation Decisions

### Status Colors in Data Explorer
- **D-01:** Status badges in Data Explorer tables (transaction status, processing status) MUST be color-coded using existing CSS badge classes: `.badge.matched` (green), `.badge.failed` (red), `.badge.warning` (amber), `.badge.processing` (blue), `.badge.unmatched` (red), `.badge.pending` (amber)
- **D-02:** The `renderDataExplorer()` function MUST use the `badge()` helper (already exists in app.js for reconciliation) instead of hardcoded `<span class="badge matched">` for status display
- **D-03:** Transaction status values (`SUCCESS`, `FAILED`, etc.) must map to appropriate badge classes, same for file processing status (`COMPLETED`, `FAILED`, `PROCESSING`, etc.)

### Dropdown Menu & Date Picker Styling
- **D-04:** Page filter dropdowns (`<select>`) and date input (`<input type="date">`) MUST have visible contrast against the dark background — fix the `.page-filters .filter-input-wrapper` background, border, and hover states
- **D-05:** The `<select>` dropdown arrow indicator needs to be visible (custom dropdown arrow icon)
- **D-06:** Date picker `<input type="date">` must use a visible calendar icon and clear text contrast against the dark surface
- **D-07:** Toolbar filter dropdown (recon-status-filter in Reconciliation page) must match the page-filters styling for consistency

### Dashboard & Insight Layout Restructure
- **D-08:** Partner selection (`renderPageFilters()`) MUST appear BELOW the metrics cards section (`renderOverview()` metrics row), not at the top of the page
- **D-09:** The "Regenerate AI Analysis" button MUST be removed from the UI since the underlying AI endpoint is non-functional for on-demand regeneration
- **D-10:** The segmented tabs container should remain but the button column removed

### Heading Hierarchy
- **D-11:** Section headings for "AI Identified Anomalies & Recommendations", "Ingested Reconciliation Files", "Raw Ingested Transactions", "Reconciliation Quality" and other section-level headings MUST be increased from `16px` to `20px` with `font-weight: 800`
- **D-12:** The AI Observation accordion title should also get a slightly larger heading
- **D-13:** Insight section ("AI Identified Anomalies & Recommendations") should be visually elevated — more top padding/margin to distinguish it as a major page section

### Data Explorer Advanced Filtering
- **D-14:** Data Explorer (`/api/v1/data/transactions` endpoint) MUST support these new query parameters:
  - `status` — filter by transaction status (already exists, needs UI integration)
  - `trace` — filter by trace ID (already exists, needs UI integration)
  - `amount_min` / `amount_max` — filter by amount range (NEW: backend + UI)
  - `date_from` / `date_to` — date range filter (NEW: backend + UI)
- **D-15:** Files endpoint (`/api/v1/data/files`) MUST support:
  - `status` — filter by processing status (already exists, needs UI integration)
  - `date_from` / `date_to` — date range filter (NEW: backend + UI)
- **D-16:** Data Explorer UI must render an expanded filter bar with all filter inputs, below the partner/date filters
- **D-17:** All API filter parameters must be optional (backward compatible with existing behavior)
- **D-18:** Amount range filtering in backend MUST use MongoDB query with `$gte`/`$lte` on `partnerData.amount` (Decimal128 field — requires string comparison or conversion)

### OpenCode's Discretion
- Exact visual styling choices for dropdown arrow, filter bar layout, badge color mapping
- Whether to use inline SVG or CSS for custom dropdown arrows
- Actual color assignment per reconciliation status value (follow existing CSS patterns)
- Filter bar UI layout (inline fields vs stacked)
- Backend implementation details for amount range filtering (MongoDB Decimal128 query approach)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source Code
- `web/app.js` — Main UI application (all rendering, routing, event binding)
- `web/styles.css` — All CSS styles (dark theme, panels, badges, filters)
- `web/index.html` — App shell (no changes expected)
- `src/api/data_explorer.py` — Data Explorer API endpoints with filter parameters

### Prior Phase Context
- `.planning/phases/13-backend-audit-ui-polish/13-CONTEXT.md` — Phase 13 UI decisions and patterns
- `.planning/phases/13-backend-audit-ui-polish/13-03-SUMMARY.md` — How UI tabs/widgets were implemented

</canonical_refs>

<specifics>
## Specific Ideas

- Existing `badge()` helper function in app.js already maps reconciliation statuses to color classes — use the same pattern for transaction/file statuses
- Page filter bar currently renders at top of every page — moving it below metrics on Dashboard is the main layout change
- The "Regenerate AI Analysis" button is in the `.insights-header-row` container — just remove the button column, keep tabs
- For amount range filtering: MongoDB stores amounts as Decimal128 in `partnerData.amount` — will need to query using string comparison or convert Decimal128 to comparable value
- Existing backend already has `trace` and `status` query params in `/api/v1/data/transactions` — only need to expose them in the UI

</specifics>

<deferred>
## Deferred Ideas

- AI-powered mapping config suggestion — already deferred from Phase 13
- Full-text search across transactions — belongs in a future data platform phase
- Export to CSV from Data Explorer — nice-to-have, not MVP
- Pagination controls in Data Explorer UI — existing API supports limit/offset but UI doesn't expose it clearly

</deferred>

---

*Phase: 15-ui-ux-polish*
*Context gathered: 2026-06-02 via user feedback*
