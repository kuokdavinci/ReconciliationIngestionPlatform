---
phase: 17-ux-refactor
reviewed: 2026-06-09T15:30:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - frontend/app.js
  - frontend/styles.css
  - src/api/operations.py
  - src/api/mappings.py
  - src/api/review_packets.py
  - src/api/copilot.py
  - src/models/copilot_action.py
  - src/models/review_packet.py
  - src/models/indexes.py
findings:
  critical: 1
  high: 4
  medium: 6
  low: 4
  total: 15
status: issues_found
---

# Phase 17: Code Review Report

**Reviewed:** 2026-06-09T15:30:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Reviewed 9 files (3672-line JavaScript SPA, 3087-line CSS, 5 Python API modules, 2 model definitions, 1 index configuration). The overall code quality is solid, with consistent patterns around error handling, async usage, and HTML escaping. However, several security-sensitive issues were found:

- **1 Critical**: Path traversal vulnerability in file upload endpoints
- **4 High**: Date parsing ambiguity, stale event listeners, sort crash risk, incomplete payload in copilot brief decisions
- **6 Medium**: Missing input validation, TOCTOU race conditions, code duplication, potential `None` dereference
- **4 Low**: Inline handlers, deep nesting, missing indexes, variable naming

The frontend is a well-structured SPA with good state management and render-token-based stale response prevention. The backend uses consistent repository patterns. Key areas needing attention: file upload security, date input ambiguity, and database update ordering.

---

## Critical Issues

### CR-01: Path traversal in file upload temp file paths

**File:** `src/api/mappings.py:510` (and 671)

**Issue:** The file upload endpoints construct temporary file paths using `file.filename` directly, allowing path traversal via `../` sequences. Additionally, `file.filename` can be `None` per FastAPI docs, which would raise `TypeError` with `Path / None`.

```python
# Line 510
temp_file_path = temp_dir / file.filename  # Path traversal via ../ in filename

# Line 671
temp_file_path = temp_dir / file.filename  # Identical issue in second endpoint
```

An attacker could send a filename like `../../tmp/malicious.csv` to write files outside the intended directory. The file is later read for processing and deleted in the `finally` block, but arbitrary file write exists in the window between creation and deletion.

**Fix:** Strip directory components from the filename before constructing the path, and handle `None`:

```python
import os

safe_name = os.path.basename(file.filename) if file.filename else f"upload_{uuid4().hex}"
temp_file_path = temp_dir / safe_name
```

---

## High Issues

### HR-01: 4-digit date parsing ambiguity (MMDD vs DDMM)

**File:** `frontend/app.js:220-223`

**Issue:** The `parseFlexibleDateInput` function treats a 4-digit string without separators (e.g., `"1206"`) as MMDD format, extracting the first two digits as month and the last two as day. However, the user-facing toast message (line 285) and the referenced format `dd/mm/yyyy` clearly indicate DDMM convention is expected. This causes a silent date inversion: input `"1206"` is interpreted as December 6th instead of the intended June 12th.

```javascript
// Line 220-223 — treats 4-digit input as MMDD
if (/^\d{4}$/.test(raw)) {
    month = Number(raw.slice(0, 2));  // actually day in DDMM convention
    day = Number(raw.slice(2, 4));    // actually month in DDMM convention
```

The month/day values are stored in the wrong variables, which affects all subsequent validation and display. Only inputs where month === day (e.g., `"0707"`) produce correct results.

**Fix:** Swap the assignment order to match DDMM convention:

```javascript
if (/^\d{4}$/.test(raw)) {
    day = Number(raw.slice(0, 2));    // first two digits = day
    month = Number(raw.slice(2, 4));  // last two digits = month
    year = fallbackYear;
}
```

Add a comment clarifying the expected DDMM order for the no-separator format.

---

### HR-02: Stale/bound event listeners on reconciliation route

**File:** `frontend/app.js:468-491`

**Issue:** The reconciliation route has an optimization that skips `view.innerHTML` replacement when already on the reconciliation page:

```javascript
const alreadyOnRecon = !!view.querySelector(".status-tabs");
if (!alreadyOnRecon) {
    view.innerHTML = loadingPanel("Loading reconciliation results...");
}
```

When the route is re-rendered (e.g., partner filter change), `bindViewActions()` at line 489 is called, which attaches new event listeners via `querySelectorAll("[data-action]")` on the existing DOM. Since `view.innerHTML` was NOT replaced, old listeners on persistent elements accumulate. Each call to `bindViewActions()` adds another listener, so repeated filter changes cause N listeners per element, executing the action N times.

**Fix:** Either (a) always replace `view.innerHTML` to ensure fresh DOM, or (b) use event delegation on the `view` container instead of per-element listeners:

```javascript
// Replace per-element listeners with delegation on #view:
view.addEventListener("click", (e) => {
    const actionEl = e.target.closest("[data-action]");
    if (!actionEl) return;
    const action = actionEl.dataset.action;
    // ... handle action
});
```

---

### HR-03: Potential TypeError in activity sort key

**File:** `src/api/operations.py:111`

**Issue:** The `_build_activity_items` function sorts activities using a key that may mix `datetime` objects with `str` values:

```python
activity.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
```

The `"timestamp"` field comes from `file.get("uploadedAt") or file.get("createdAt")` (line 75), where the values are `datetime` objects from `model_dump()` (not serialized to strings). If a timestamp is `None`, the `or` chain falls through to `""`, but if other items have `datetime` objects, the comparison `datetime > str` raises `TypeError` in Python 3.

This is unlikely in practice because all models supply a default `createdAt`, but any code path producing an activity item without a timestamp would crash this sort.

**Fix:** Convert all timestamps to ISO strings before sorting, or use a sort key that handles both types:

```python
activity.sort(
    key=lambda item: str(item.get("timestamp") or ""),
    reverse=True,
)
```

---

### HR-04: Copilot brief decisions skip scope type in payload

**File:** `frontend/app.js:3481-3493`

**Issue:** The `executeCopilotAction` function sends approval/rejection requests without the `scopeType` field:

```javascript
body: JSON.stringify({
    partner: state.partner,
    date: state.date,
    reviewedBy: "Administrator",
    // scopeType is MISSING — scope overrides set in the review drawer
    // are not propagated when approving via the Copilot Brief modal
}),
```

When a user selects a scope override in the Review Center drawer's dropdown and then approves via the Copilot Brief (step 3 decision buttons), the scope choice is silently dropped. The backend receives `scopeType=None` and preserves the original scope, potentially reconciling with the wrong scope strategy.

**Fix:** Read the scope override from `state.overrideScopes` and include it in the payload:

```javascript
body: JSON.stringify({
    partner: state.partner,
    date: state.date,
    reviewedBy: "Administrator",
    scopeType: state.overrideScopes?.[state.selectedReviewPacketId] || undefined,
}),
```

---

## Medium Issues

### MD-01: Upload file.filename can be None

**File:** `src/api/mappings.py:510,671`

**Issue:** The two multipart upload endpoints call `temp_dir / file.filename` without checking if `file.filename` is `None`. According to FastAPI docs, `UploadFile.filename` can be `None` when the client omits the filename. `Path / None` raises `TypeError: unsupported operand type(s) for /: 'PosixPath' and 'NoneType'`.

**Fix:** Add a fallback:

```python
safe_name = file.filename or f"upload_{uuid4().hex}"
temp_file_path = temp_dir / safe_name
```

Also apply the `os.path.basename` sanitization from CR-01.

---

### MD-02: test_mapping lacks input type validation

**File:** `src/api/mappings.py:577`

**Issue:** The `test_mapping` endpoint accepts an arbitrary `dict` payload and calls `int(mapping["column"])` without validating that the value is numeric. A malformed request with `"column": "ABC"` would crash with `ValueError: invalid literal for int() with base 10: 'ABC'`.

```python
col_idx = int(mapping["column"]) - 1  # crashes if column is non-numeric
```

**Fix:** Add type validation or use a safe conversion:

```python
try:
    col_idx = int(mapping["column"]) - 1
except (ValueError, TypeError):
    continue  # skip invalid column references
```

---

### MD-03: TOCTOU race condition in approve_activate_packet scope update

**File:** `src/api/review_packets.py:359-371`

**Issue:** The scope update is performed independently and committed before the main approval operation. If the approval fails (e.g., because another request already processed the packet), the scope change persists while the packet remains unapproved:

```python
if payload.scope_type:
    packet.scope_type = payload.scope_type
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": {"scopeType": payload.scope_type}}   # scope committed here
    )
    # ... later approval operations might fail
```

And at lines 344-356, the packet is fetched, then its status checked, but between the status check and the scope update, another request could change the packet's status.

**Fix:** Combine the scope update with the status update in `_mark_packet` to ensure atomicity. Either (a) pass scope through to `_mark_packet` and set it atomically with the status, or (b) use a MongoDB transaction.

---

### MD-04: Missing partner config causes broken version API call

**File:** `frontend/app.js:3286`

**Issue:** When proceeding from Step 2 to Step 3 in Mapping Studio, the code fetches schema versions using `state.studio.config.partner`. If the config has no `partner` field (e.g., pasted JSON was edited to remove it), the URL becomes `/api/v1/mapping/versions?partner=undefined`, returning incorrect results:

```javascript
return fetch(`/api/v1/mapping/versions?partner=${encodeURIComponent(state.studio.config.partner)}`);
```

**Fix:** Default to the current state partner if config partner is missing:

```javascript
const partner = state.studio.config?.partner || state.partner;
return fetch(`/api/v1/mapping/versions?partner=${encodeURIComponent(partner)}`);
```

---

### MD-05: Code duplication in scope update logic

**File:** `src/api/review_packets.py:359-371` and `:438-450`

**Issue:** The exact same scope-update-with-source-file-sync block is duplicated in both `approve_activate_packet` and `approve_keep_current_packet`. This is a maintenance risk — any change to the scope logic must be applied in both places.

**Fix:** Extract into a shared helper:

```python
async def _apply_scope_override(request, repo, packet_id, packet, scope_type):
    if not scope_type:
        return
    packet.scope_type = scope_type
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": {"scopeType": scope_type}}
    )
    if packet.source_file_id:
        db = _get_db(request)
        file_repo = ReconciliationFileRepository(db)
        await file_repo.update_one(
            {"_id": packet.source_file_id},
            {"scopeType": scope_type}
        )
```

---

### MD-06: Virtual packet "keep current" action fails via copilot brief

**File:** `src/api/copilot.py:104-113`

**Issue:** The `approve_keep_current` action handler requires a `review_item_id` and raises an error if absent:

```python
if not review_item_id:
    raise HTTPException(status_code=400, detail="No review packet is available for this action.")
```

However, the Copilot Brief in the frontend shows this action button for all proposals, including "virtual" packets (standalone draft mappings without a review packet). Users clicking "Keep current runtime" for a virtual mapping config get an error with no explanation.

**Fix:** Handle the `draft_mapping_id` fallback similarly to `approve_activate_next_runtime` and `reject_proposal`, which both support direct mapping config operations:

```python
if review_item_id:
    result = await approve_keep_current_packet(request, review_item_id, ...)
elif draft_mapping_id:
    # For virtual packets: just mark config as approved without activating
    result = await approve_mapping_config(request, draft_mapping_id, ...)
else:
    raise HTTPException(...)
```

---

## Low Issues

### LO-01: Inline onclick handler in template

**File:** `frontend/app.js:2022`

**Issue:** The "Generate Draft" button uses an inline `onclick` attribute instead of the project's consistent `addEventListener` pattern:

```html
<button class="button primary" style="width: 100%;" onclick="document.getElementById('studio-excel-upload').click()">
```

This is inconsistent with all other event bindings which use `addEventListener` via `bindViewActions()`. It also introduces a subtle issue: since `onclick` references `document` globally, it can't be properly scoped by the IIFE.

**Fix:** Use `addEventListener` in `bindViewActions()` via a `data-action` attribute.

---

### LO-02: Deeply nested event dispatch in bindViewActions

**File:** `frontend/app.js:2584-3370`

**Issue:** The `bindViewActions` function is a single ~800-line function containing a deeply nested switch-like chain of `if (action === ...)` blocks inside `querySelectorAll("[data-action]")`. This makes the function difficult to maintain, test, and reason about.

**Fix:** Extract each action handler into a named function or an object map:

```javascript
const actionHandlers = {
    "run-job": (el) => { ... },
    "copilot-action": (el) => { ... },
    "approve-config": (el) => { ... },
    // ...
};
```

Then dispatch from a single delegation listener:

```javascript
view.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    const action = el?.dataset.action;
    if (action && actionHandlers[action]) actionHandlers[action](el, e);
});
```

---

### LO-03: Confusing variable name `actions_query` reused for packets

**File:** `src/api/operations.py:148`

**Issue:** The variable `actions_query` (defined at line 140 for the CopilotAction query) is reused for the ReviewPacket query at line 148:

```python
actions_query: dict = {}
if partner:
    actions_query["partner"] = partner

files = await file_repo.find_many(file_query)
mappings = await mapping_repo.find_many(mappings_query)
actions = await action_repo.find_many(actions_query)
packets = await packet_repo.find_many(actions_query)  # reuses actions_query
```

While functionally correct (both queries filter by `partner`), reusing a variable named `actions_query` for packets is misleading and harms readability.

**Fix:** Define a separate `packets_query` variable:

```python
packets_query = {"partner": partner} if partner else {}
packets = await packet_repo.find_many(packets_query)
```

---

### LO-04: No database indexes for mapping config history collection

**File:** `src/models/indexes.py` (missing definition)

**Issue:** The `reconciliation_mapping_config_history` collection is used by `mappings.py:622-627` (history write on publish) and `mappings.py:637-647` (version listing sorted by `publishedAt`). However, no indexes are defined for this collection in `indexes.py`. The `list_versions` endpoint queries with `{"partner": partner}` and sorts by `publishedAt`, which requires a compound index for efficiency.

**Fix:** Add index definition:

```python
"reconciliation_mapping_config_history": [
    IndexModel(
        [("partner", ASCENDING), ("publishedAt", ASCENDING)],
        name="idx_history_partner_published",
    ),
],
```

---

_Reviewed: 2026-06-09T15:30:00Z_
_Reviewer: OpenCode (gsd-code-reviewer)_
_Depth: standard_
