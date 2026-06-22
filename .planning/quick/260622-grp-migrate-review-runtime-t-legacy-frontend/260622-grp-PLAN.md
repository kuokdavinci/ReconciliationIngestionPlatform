---
phase: 260622-grp
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend-next/src/lib/review-runtime.ts
  - frontend-next/src/types/review-center.ts
  - frontend-next/src/lib/api/review-center.ts
  - frontend-next/src/components/review-center/guided-review-modal.tsx
  - frontend-next/src/components/review-center/review-center.module.css
autonomous: true
requirements: ["RUNTIME-01"]
must_haves:
  truths:
    - "User can see a progress bar showing pass/warn/fail percentage of runtime validation"
    - "User can see version staleness warning if draft was edited after last validation"
    - "User can browse a trace gallery showing before/after (source → normalized) for each sample row"
    - "User can open a trace detail modal showing a 7-column field-level trace table"
    - "Validation issues display human-readable suggestions per error code"
  artifacts:
    - path: "frontend-next/src/lib/review-runtime.ts"
      provides: "Pure helper functions migrated from legacy render.js"
      min_lines: 120
    - path: "frontend-next/src/types/review-center.ts"
      provides: "RuntimeFieldTrace and RuntimeTraceSample types"
      contains: "interface RuntimeFieldTrace"
    - path: "frontend-next/src/components/review-center/guided-review-modal.tsx"
      provides: "Enhanced Step 3 with progress bar, trace gallery, detail modal"
      contains: "traceDetailSampleIndex"
  key_links:
    - from: "guided-review-modal.tsx (Step 3)"
      to: "lib/review-runtime.ts"
      via: "import { getRuntimeValidationState, collectValidationIssues }"
    - from: "guided-review-modal.tsx (Step 3)"
      to: "lib/api/review-center.ts normalizeRuntimeValidation"
      via: "traceSamples passed through RuntimeValidationResult"
---

<objective>
Migrate runtime review helpers from legacy `frontend/src/features/review-runtime/render.js` to the Next.js frontend, and enhance Step 3 of the guided-review-modal with a progress bar, before/after trace gallery, and a trace detail modal with field-level trace table.

Purpose: Give operators the same runtime inspection capabilities they had in the legacy UI — pass/fail progress visualization, source→normalized trace browsing, and field-level detail drill-down — now inside the guided review wizard.
Output:
1. `frontend-next/src/lib/review-runtime.ts` — Pure TS helper functions (getRuntimeValidationState, getValidationSuggestion, collectValidationIssues, collectRuntimeFieldStats, collectCandidateColumns)
2. Updated `types/review-center.ts` with `RuntimeFieldTrace` and `RuntimeTraceSample` interfaces
3. Updated `lib/api/review-center.ts` to pass through raw traceSamples
4. Enhanced Step 3 in `guided-review-modal.tsx`: progress bar + trace gallery + trace detail modal
5. New CSS classes in `review-center.module.css` for progress bar, trace gallery cards, and detail modal
</objective>

<execution_context>
@$HOME/.config/opencode/get-shit-done/workflows/execute-plan.md
@$HOME/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
- Legacy source patterns: `frontend/src/features/review-runtime/render.js` (pure helper functions, no React — adapt to TS + React)
- Current Step 3: `frontend-next/src/components/review-center/guided-review-modal.tsx` lines 584–696
- Existing types: `frontend-next/src/types/review-center.ts` (ValidationGate, RuntimeValidationResult, etc.)
- API normalization: `frontend-next/src/lib/api/review-center.ts` (normalizeRuntimeValidation already extracts traceSamples but discards them)
- Styling conventions: `review-center.module.css` (CSS modules, dark theme, BEM-like naming with camelCase)
- Mock data shape: `frontend-next/src/lib/state/mock-review-center-data.ts` has traceSamples with row, normalizedData, fieldTraces

### Data shape for trace samples (from backend gate details):
```typescript
interface RuntimeFieldTrace {
  path: string;            // canonical field name
  sourceField: string | null;  // partner field name
  sourceValue?: string | null;
  outputValue?: string | null;
  status: "ok" | "warning" | "error";
  type?: string;           // transform type
  column?: number;
  errorCode?: string;
  errorMessage?: string;
}

// A trace sample = one sample row processed through the mapping
interface RuntimeTraceSample {
  row: number;
  normalizedData: Record<string, string | null>;
  fieldTraces: RuntimeFieldTrace[];
  buildErrors?: Array<{ field: string; errorCode: string; reason: string }>;
}
```

### Interfaces to extract from existing code for Task 2 executor:
Types consumed in Task 2 (already exist in types/review-center.ts):
```
RuntimeValidationResult.validationStatus: "PASSED" | "WARNING" | "FAILED"
RuntimeValidationResult.summary.validRowsPercent: number
RuntimeValidationResult.summary.rowsChecked: number
RuntimeValidationResult.summary.errorRows: number
RuntimeValidationResult.fieldResults: Array<{ canonicalField, sourceColumn, status, issue }>
RuntimeValidationResult.previewRows: Array<{ id, values, invalidFields? }>
RuntimeValidationResult.topIssues: Array<{ type, message, affectedRows, severity }>
```

Functions exported from lib/review-runtime.ts (consumed in Task 2):
```
getRuntimeValidationState(packet: ReviewPacket): { hasValidation, isStale, failedRows, canProceed, summaryLabel, runtimeGate, currentVersion, validatedVersion, validatedAt }
getValidationSuggestion(code: string, field?: string): string
collectValidationIssues(runtimeGate: ValidationGate): Array<{ code, field, row, message, suggestion }>
collectRuntimeFieldStats(runtimeGate: ValidationGate): Array<{ field, ok, warning, error }>
```
</context>

<interfaces>
<!-- Key types and contracts the executor needs. Extracted from codebase. -->

**From `frontend-next/src/types/review-center.ts` (read by both tasks):**
```typescript
interface ValidationGate {
  gateKey: string;
  status: string;
  label: string;
  message?: string;
  details?: Record<string, unknown>;
}

interface ReviewPacket {
  _id: string;
  // ... (full interface at types/review-center.ts)
  validationGates: ValidationGate[];
  runtimeValidation?: RuntimeValidationResult | null;
  draftMappingId?: string;
  // ...
}

interface RuntimeValidationResult {
  validationStatus: "PASSED" | "WARNING" | "FAILED";
  canSave: boolean;
  summary: { rowsChecked, mappedFields, totalFields, requiredFieldsPassed, requiredFieldsTotal, validRows, errorRows, validRowsPercent };
  fieldResults: RuntimeValidationFieldResult[];
  previewRows: RuntimeValidationPreviewRow[];
  topIssues: RuntimeValidationTopIssue[];
  likelyCause?: string;
}
```

**From `frontend-next/src/lib/state/mock-review-center-data.ts` — trace sample shape:**
```typescript
// Each element in details.traceSamples
{
  row: 2,
  normalizedData: { transactionId: "MOMO_1001", amount: "105000", status: "SUCCESS", paidAt: "2026-06-10 09:15", currency: "VND" },
  fieldTraces: [
    { path: "transactionId", sourceField: "msTransId", status: "ok", sourceValue?: "...", outputValue?: "..." },
    { path: "paidAt", sourceField: "msNgayHoanThanh", status: "error", errorCode: "missing_date", errorMessage: "Missing paidAt value" },
  ],
  buildErrors?: [{ field: "...", errorCode: "CANONICAL_BUILD_FAILED", reason: "..." }]
}
```
</interfaces>

<tasks>

<task type="auto" tdd="false">
  <name>Task 1: Create review-runtime helper library + update types + pass through traceSamples in API normalization</name>
  <files>
    frontend-next/src/lib/review-runtime.ts (NEW)
    frontend-next/src/types/review-center.ts (MODIFY)
    frontend-next/src/lib/api/review-center.ts (MODIFY)
  </files>
  <action>
    **Part A — Add types to `types/review-center.ts`:**

    Before the `ReviewPacket` interface, add these new type definitions:

    ```typescript
    export interface RuntimeFieldTrace {
      path: string;
      sourceField: string | null;
      sourceValue?: string | number | null;
      outputValue?: string | number | null;
      status: "ok" | "warning" | "error";
      type?: string;
      column?: number;
      errorCode?: string;
      errorMessage?: string;
    }

    export interface RuntimeTraceSample {
      row: number;
      normalizedData: Record<string, string | number | null>;
      fieldTraces: RuntimeFieldTrace[];
      buildErrors?: Array<{ field: string; errorCode: string; reason: string }>;
    }
    ```

    Then add `traceSamples?: RuntimeTraceSample[]` to the `RuntimeValidationResult` interface.

    **Part B — Update `lib/api/review-center.ts`:**

    In `normalizeRuntimeValidation`, after the existing code that extracts `traceSamples`, add the raw samples to the return value:

    ```typescript
    traceSamples: traceSamples.map(sample => ({
      row: Number(sample.row ?? 0),
      normalizedData: (sample.normalizedData as Record<string, string | number | null>) || {},
      fieldTraces: (Array.isArray(sample.fieldTraces) ? sample.fieldTraces : []).map((trace: Record<string, unknown>) => ({
        path: String(trace.path ?? ""),
        sourceField: trace.sourceField != null ? String(trace.sourceField) : null,
        sourceValue: trace.sourceValue ?? null,
        outputValue: trace.outputValue ?? null,
        status: (String(trace.status ?? "ok") as "ok" | "warning" | "error"),
        type: trace.type != null ? String(trace.type) : undefined,
        column: trace.column != null ? Number(trace.column) : undefined,
        errorCode: trace.errorCode != null ? String(trace.errorCode) : undefined,
        errorMessage: trace.errorMessage != null ? String(trace.errorMessage) : undefined,
      })),
      buildErrors: Array.isArray(sample.buildErrors) ? sample.buildErrors.map((err: Record<string, unknown>) => ({
        field: String(err.field ?? ""),
        errorCode: String(err.errorCode ?? "CANONICAL_BUILD_FAILED"),
        reason: String(err.reason ?? ""),
      })) : undefined,
    })) as RuntimeTraceSample[],
    ```

    Add the import at top:
    ```typescript
    import type { RuntimeTraceSample } from "@/types/review-center";
    ```

    **Part C — Create `lib/review-runtime.ts`:**

    This is a pure TS module (no React, no JSX). Export the following functions adapted from legacy `render.js`. Do NOT include any rendering/HTML functions — those become React components in Task 2.

    ```typescript
    const VALIDATION_SUGGESTIONS: Record<string, string> = {
      SOURCE_FIELD_NOT_FOUND: "Source field does not exist in sample data. Re-map this target to an existing partner field.",
      MISSING_REQUIRED_FIELD: "Required field '{field}' is missing. Map a partner field to this canonical field.",
      INVALID_DECIMAL: "Map the partner numeric amount field to 'amount' and ensure the sample value is numeric.",
      INVALID_DATE: "Check the source date field and ensure it matches a supported runtime date format.",
      UNMAPPED_VALUE: "Add a mapping rule for this partner value or configure a fallback rule.",
      INVALID_CANONICAL_STATUS: "Map the partner status into one of SUCCESS, FAILED, PENDING, REVERSED.",
    };

    export interface RuntimeValidationState {
      runtimeGate: ValidationGate | null;
      currentVersion: string | null;
      validatedVersion: string | null;
      validatedAt: string | null;
      hasValidation: boolean;
      isStale: boolean;
      failedRows: number;
      canProceed: boolean;
      summaryLabel: string;
    }
    ```

    Functions (each from the legacy source, adapted to TS):
    1. `export function getDraftMappingVersion(packet: ReviewPacket): string | null` — extracts draftMappingVersion from packet.draftMappingId, packet.runtimeValidation?.likelyCause, or packet.validationGates details
    2. `export function getRuntimeValidationState(packet: ReviewPacket): RuntimeValidationState` — finds runtime_validation gate, computes staleness, canProceed, summaryLabel
    3. `export function getValidationSuggestion(code: string, field?: string): string` — looks up VALIDATION_SUGGESTIONS, replaces "{field}" placeholder
    4. `export function collectValidationIssues(runtimeGate: ValidationGate): Array<{ code: string; field: string; row: number; message: string; suggestion: string }>` — deduplicates from traceSamples fieldTraces+buildErrors
    5. `export function collectRuntimeFieldStats(runtimeGate: ValidationGate): Array<{ field: string; ok: number; warning: number; error: number }>` — aggregates field-level counts per trace.status, sorted by error desc

    Import types at top:
    ```typescript
    import type { ReviewPacket, ValidationGate, RuntimeTraceSample } from "@/types/review-center";
    ```

    **Per D-01** (maintaining legacy behavior): `collectValidationIssues` must use the same dedup key logic (`${errorCode}:${path}:${errorMessage}`) as legacy render.js

    Do NOT create test files. Do NOT add any React imports.
  </action>
  <verify>
    <automated>
      npx tsc --noEmit --strict frontend-next/src/lib/review-runtime.ts 2>&1 | head -20
    </automated>
  </verify>
  <done>
    - lib/review-runtime.ts exists with 5 exported helper functions + VALIDATION_SUGGESTIONS const
    - types/review-center.ts has RuntimeFieldTrace, RuntimeTraceSample, and traceSamples on RuntimeValidationResult
    - lib/api/review-center.ts normalizes and passes through traceSamples
    - TypeScript compilation passes for all modified files
  </done>
</task>

<task type="auto" tdd="false">
  <name>Task 2: Enhance Step 3 with progress bar, trace gallery, and trace detail modal</name>
  <files>
    frontend-next/src/components/review-center/guided-review-modal.tsx (MODIFY)
    frontend-next/src/components/review-center/review-center.module.css (MODIFY)
  </files>
  <action>
    **Dependency:** Task 1 must complete first (lib/review-runtime.ts, updated types, traceSamples in API normalization).

    **Part A — CSS classes to add to `review-center.module.css`:**

    Add these new classes (follow existing naming conventions, CSS modules, dark-theme):

    ```css
    /* ── Progress bar (3-segment: green / amber / red) ── */
    .progressBarWrap {
      padding: 16px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.015);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .progressLabel {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
    }
    .progressTitle {
      font-size: 11px;
      font-weight: 800;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .progressRate {
      font-size: 12px;
      font-weight: 700;
    }
    .progressBar {
      height: 8px;
      border-radius: 4px;
      overflow: hidden;
      background: rgba(255, 255, 255, 0.06);
      display: flex;
      margin-bottom: 12px;
    }
    .progressSegmentGreen {
      height: 100%;
      background: #10B981;
      transition: width 0.3s ease;
    }
    .progressSegmentAmber {
      height: 100%;
      background: #F59E0B;
      transition: width 0.3s ease;
    }
    .progressSegmentRed {
      height: 100%;
      background: #EF4444;
      transition: width 0.3s ease;
    }
    .progressLegend {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      font-size: 11.5px;
    }
    .progressLegendItem {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .progressDot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .progressLegendCount {
      font-weight: 700;
      color: #fff;
    }
    .progressFreshness {
      border-left: 1px solid rgba(255, 255, 255, 0.06);
      padding-left: 24px;
    }

    /* ── Trace Gallery ── */
    .traceGallery {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .traceCard {
      padding: 12px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    .traceCardHeader {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
      flex-wrap: wrap;
      padding: 0 2px;
    }
    .traceCardTitle {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .traceCardSampleName {
      font-size: 13px;
      font-weight: 700;
      color: #fff;
    }
    .traceColumns {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .traceColumn {
      padding: 12px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.015);
    }
    .traceColumnTitle {
      font-size: 11px;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 8px;
    }
    .traceRow {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 6px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }
    .traceRowKey {
      font-family: var(--font-mono);
      font-size: 11.5px;
      color: var(--text-muted);
    }
    .traceRowValue {
      font-family: var(--font-mono);
      font-size: 11.5px;
      text-align: right;
      word-break: break-word;
      color: #fff;
    }
    .traceBuildError {
      margin-top: 10px;
      font-size: 11px;
      color: #fca5a5;
    }
    .traceDetailButton {
      padding: 2px;
      min-width: unset;
      height: unset;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      color: var(--brand-primary);
      background: transparent;
      border: none;
      font-size: 18px;
    }

    /* ── Trace Detail Modal (inline overlay within Step 3) ── */
    .traceDetailOverlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.62);
      display: grid;
      align-items: center;
      justify-content: center;
      z-index: 100;
      padding: 24px;
    }
    .traceDetailPanel {
      background: #111;
      padding: 24px;
      border-radius: 12px;
      max-width: 920px;
      width: 100%;
      max-height: calc(100vh - 48px);
      overflow-y: auto;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .traceDetailHeader {
      display: flex;
      justify-content: space-between;
      margin-bottom: 20px;
    }
    .traceDetailTitle {
      margin: 0;
      font-size: 16px;
      color: #fff;
    }
    .traceDetailSubtitle {
      margin: 6px 0 0;
      font-size: 12px;
      color: var(--text-muted);
    }
    .traceDetailClose {
      background: none;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 18px;
      padding: 4px;
    }
    .traceDetailClose:hover {
      color: #fff;
    }
    .traceDetailColumns {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .traceDetailSection {
      padding: 12px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.015);
    }
    .traceDetailSectionTitle {
      font-size: 11px;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 8px;
    }
    .traceTable {
      width: 100%;
      border-collapse: collapse;
      font-size: 11.5px;
    }
    .traceTable th {
      padding: 6px 8px;
      text-align: left;
      font-size: 10.5px;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    .traceTable td {
      padding: 8px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    .traceTable tr:last-child td {
      border-bottom: none;
    }
    .traceBuildErrorBlock {
      margin-top: 12px;
      padding: 12px;
      border: 1px solid rgba(239, 68, 68, 0.18);
      border-radius: 8px;
      background: rgba(239, 68, 68, 0.05);
    }

    /* ── Freshness section (inline in progress bar area) ── */
    .freshnessGrid {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 24px;
      align-items: center;
    }
    .freshnessBadge {
      display: inline-flex;
      padding: 2px 8px;
      font-size: 10px;
      border-radius: 4px;
      font-weight: 700;
    }
    .freshnessMatched {
      background: rgba(14, 203, 129, 0.12);
      color: #0ecb81;
    }
    .freshnessWarning {
      background: rgba(240, 185, 11, 0.12);
      color: #f0b90b;
    }
    .freshnessNeutral {
      background: rgba(255, 255, 255, 0.06);
      color: var(--text-muted);
    }
    .freshnessVersion {
      font-size: 11px;
      color: var(--text-muted);
      margin-top: 4px;
    }
    .freshnessVersionCode {
      background: rgba(0, 0, 0, 0.2);
      padding: 2px 6px;
      border-radius: 4px;
      font-family: var(--font-mono);
    }
    ```

    **Part B — Update imports in `guided-review-modal.tsx`:**

    Add these imports at the top:
    ```typescript
    import {
      getRuntimeValidationState,
      getValidationSuggestion,
      collectValidationIssues,
    } from "@/lib/review-runtime";
    ```

    **Part C — Add state for trace detail modal:**

    After the existing `const [isValidatingRuntime, setIsValidatingRuntime] = useState(false);` (line 48), add:
    ```typescript
    const [traceDetailSampleIndex, setTraceDetailSampleIndex] = useState<number | null>(null);
    ```

    **Part D — Compute validation state using the new helper:**

    Replace the existing `validationState` useMemo block (lines 286–312) with one that uses the helper. However, keep it a useMemo and keep it compatible with the existing UI (banner, badge). Add the helper's output alongside existing fields:

    ```typescript
    const runtimeValidationState = useMemo(() => {
      if (!localPacket) return null;
      return getRuntimeValidationState(localPacket);
    }, [localPacket]);
    ```

    Keep the existing `validationState` useMemo as-is for the banner (it uses `styles.validationPassed` etc. which are CSS module classes). The new `runtimeValidationState` adds `.isStale`, `.summaryLabel`, etc.

    **Part E — Insert progress bar after the validation banner and metric pills:**

    After the `{summary && (...)}` metric pills section (after line 615), add:

    ```tsx
    {/* Progress bar + freshness */}
    {runtimeValidationState?.runtimeGate && (
      <div className={styles.progressBarWrap}>
        <div className={styles.freshnessGrid}>
          <div>
            <div className={styles.progressLabel}>
              <span className={styles.progressTitle}>Runtime Coverage</span>
              <span className={styles.progressRate} style={{ color: summary ? (summary.validRowsPercent >= 80 ? "#10B981" : summary.validRowsPercent >= 50 ? "#F59E0B" : "#EF4444") : undefined }}>
                {summary ? `${Math.round(summary.validRowsPercent)}% pass rate` : ""}
              </span>
            </div>
            {summary && (
              <>
                <div className={styles.progressBar}>
                  <div className={styles.progressSegmentGreen} style={{ width: `${Math.max(summary.validRowsPercent, 0)}%` }} />
                  {summary.errorRows > 0 && summary.validRowsPercent < 100 && (
                    <div className={styles.progressSegmentRed} style={{ width: `${Math.max(100 - summary.validRowsPercent, 0)}%` }} />
                  )}
                </div>
                <div className={styles.progressLegend}>
                  <span className={styles.progressLegendItem}>
                    <span className={styles.progressDot} style={{ background: "#10B981" }} />
                    <span><strong className={styles.progressLegendCount}>{summary.rowsChecked - summary.errorRows}</strong> success</span>
                  </span>
                  {summary.errorRows > 0 && (
                    <span className={styles.progressLegendItem}>
                      <span className={styles.progressDot} style={{ background: "#EF4444" }} />
                      <span><strong className={styles.progressLegendCount}>{summary.errorRows}</strong> failed</span>
                    </span>
                  )}
                  <span style={{ color: "var(--text-muted)" }}>
                    <strong className={styles.progressLegendCount}>{summary.rowsChecked}</strong> sampled
                  </span>
                </div>
              </>
            )}
          </div>
          <div className={styles.progressFreshness}>
            <div className={styles.progressTitle} style={{ marginBottom: 8 }}>Validation Freshness</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <span className={`${styles.freshnessBadge} ${
                runtimeValidationState.isStale ? styles.freshnessWarning
                : runtimeValidationState.hasValidation ? styles.freshnessMatched
                : styles.freshnessNeutral
              }`}>
                {runtimeValidationState.summaryLabel}
              </span>
              <span className={`${styles.freshnessBadge} ${styles.freshnessNeutral}`}>
                Draft {runtimeValidationState.currentVersion || "-"}
              </span>
            </div>
            <div className={styles.freshnessVersion}>
              Validated on <code className={styles.freshnessVersionCode}>v{runtimeValidationState.validatedVersion || "-"}</code>
            </div>
          </div>
        </div>
      </div>
    )}
    ```

    **Part F — Insert trace gallery after field results table:**

    After the `</section>` closing the field results table (after line 643), add:

    ```tsx
    {/* Trace gallery: before/after source → normalized */}
    {localPacket.runtimeValidation?.traceSamples && localPacket.runtimeValidation.traceSamples.length > 0 && (
      <section className={styles.sectionCard}>
        <h5 className={styles.sectionCardTitle}>Runtime Trace Review</h5>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 10 }}>
          <span style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", color: "var(--text-muted)" }}>Sample Trace Gallery</span>
          <span className={`${styles.freshnessBadge} ${styles.freshnessNeutral}`}>
            {localPacket.runtimeValidation.traceSamples.length} rows
          </span>
        </div>
        <div className={styles.traceGallery}>
          {localPacket.runtimeValidation.traceSamples.slice(0, 5).map((sample, idx) => {
            const hasError = sample.fieldTraces.some(t => t.status === "error");
            const hasWarning = sample.fieldTraces.some(t => t.status === "warning");
            const tone = hasError ? "critical" : hasWarning ? "medium" : "low";
            const label = hasError ? "Failed" : hasWarning ? "Warning" : "Passed";
            const sourceFields = sample.fieldTraces.filter(t => t.sourceField || t.sourceValue != null);
            const normalizedEntries = Object.entries(sample.normalizedData).filter(([, v]) => v != null && v !== "");

            return (
              <div key={sample.row} className={styles.traceCard}>
                <div className={styles.traceCardHeader}>
                  <div className={styles.traceCardTitle}>
                    <strong className={styles.traceCardSampleName}>Sample Row {sample.row}</strong>
                    <Badge severity={tone as any}>{label}</Badge>
                  </div>
                  <button
                    className={styles.traceDetailButton}
                    onClick={() => setTraceDetailSampleIndex(idx)}
                    title="View field-level detail"
                    type="button"
                  >
                    🔍
                  </button>
                </div>
                <div className={styles.traceColumns}>
                  <div className={styles.traceColumn}>
                    <div className={styles.traceColumnTitle}>Before / Raw Source</div>
                    {sourceFields.length > 0 ? sourceFields.map((trace, ti) => (
                      <div key={ti} className={styles.traceRow}>
                        <span className={styles.traceRowKey}>{trace.sourceField || trace.path || "-"}</span>
                        <span className={styles.traceRowValue}>{trace.sourceValue ?? "-"}</span>
                      </div>
                    )) : <span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>No source values</span>}
                  </div>
                  <div className={styles.traceColumn}>
                    <div className={styles.traceColumnTitle}>After / Normalized Output</div>
                    {normalizedEntries.length > 0 ? normalizedEntries.map(([key, value]) => (
                      <div key={key} className={styles.traceRow}>
                        <span className={styles.traceRowKey}>{key}</span>
                        <span className={styles.traceRowValue}>{value ?? "-"}</span>
                      </div>
                    )) : <span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>No normalized output</span>}
                  </div>
                </div>
                {sample.buildErrors && sample.buildErrors.length > 0 && (
                  <div className={styles.traceBuildError}>
                    {sample.buildErrors.length} canonical build error{sample.buildErrors.length !== 1 ? "s" : ""}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>
    )}
    ```

    Use `🔍` as the detail button icon (simple, no icon library dependency).

    **Part G — Insert trace detail modal overlay:**

    After the closing `</section>` of the issues list (after line 688), add the detail modal overlay. This is an inline overlay (separate `div` with `position: fixed`) that renders when `traceDetailSampleIndex` is not null:

    ```tsx
    {/* Trace Detail Modal Overlay */}
    {traceDetailSampleIndex !== null && localPacket.runtimeValidation?.traceSamples && (
      <div className={styles.traceDetailOverlay} onClick={() => setTraceDetailSampleIndex(null)}>
        <div className={styles.traceDetailPanel} onClick={e => e.stopPropagation()}>
          {(() => {
            const sample = localPacket.runtimeValidation!.traceSamples![traceDetailSampleIndex];
            if (!sample) return null;
            const sourceFields = sample.fieldTraces.filter(t => t.sourceField || t.sourceValue != null || t.path);
            const normalizedEntries = Object.entries(sample.normalizedData).filter(([, v]) => v != null && v !== "");
            return (
              <>
                <div className={styles.traceDetailHeader}>
                  <div>
                    <h3 className={styles.traceDetailTitle}>Runtime Trace Detail</h3>
                    <p className={styles.traceDetailSubtitle}>Sample {sample.row}</p>
                  </div>
                  <button className={styles.traceDetailClose} onClick={() => setTraceDetailSampleIndex(null)}>✕</button>
                </div>
                <div className={styles.traceDetailColumns}>
                  <div className={styles.traceDetailSection}>
                    <div className={styles.traceDetailSectionTitle}>Raw Source Snapshot</div>
                    {sourceFields.length > 0 ? sourceFields.map((trace, ti) => (
                      <div key={ti} className={styles.traceRow}>
                        <span className={styles.traceRowKey}>{trace.sourceField || trace.path || "-"}</span>
                        <span className={styles.traceRowValue}>{trace.sourceValue ?? "-"}</span>
                      </div>
                    )) : <span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>No source values</span>}
                  </div>
                  <div className={styles.traceDetailSection}>
                    <div className={styles.traceDetailSectionTitle}>Normalized Output</div>
                    {normalizedEntries.length > 0 ? normalizedEntries.map(([key, value]) => (
                      <div key={key} className={styles.traceRow}>
                        <span className={styles.traceRowKey}>{key}</span>
                        <span className={styles.traceRowValue}>{value ?? "-"}</span>
                      </div>
                    )) : <span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>No normalized output</span>}
                  </div>
                </div>
                <div style={{ marginTop: 12 }}>
                  <div className={styles.traceDetailSectionTitle}>Field-Level Trace</div>
                  <div style={{ overflowX: "auto" }}>
                    <table className={styles.traceTable}>
                      <thead>
                        <tr>
                          <th>Raw Partner Field</th>
                          <th>Raw Partner Value</th>
                          <th>Target Internal Field</th>
                          <th>Transform</th>
                          <th>Final Normalized Value</th>
                          <th>Validation Status</th>
                          <th>Failure Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sample.fieldTraces.map((trace, ti) => (
                          <tr key={ti}>
                            <td style={{ fontFamily: "var(--font-mono)" }}>{trace.sourceField || (trace.column != null ? `Column ${trace.column}` : trace.type === "CONSTANT" ? "Constant" : "-")}</td>
                            <td style={{ fontFamily: "var(--font-mono)" }}>{trace.sourceValue ?? "-"}</td>
                            <td style={{ fontFamily: "var(--font-mono)" }}>{trace.path || "-"}</td>
                            <td>{trace.type || "-"}</td>
                            <td style={{ fontFamily: "var(--font-mono)" }}>{trace.outputValue ?? "-"}</td>
                            <td style={{ color: trace.status === "error" ? "#ef4444" : trace.status === "warning" ? "#f59e0b" : "#10B981", textTransform: "capitalize" }}>{trace.status}</td>
                            <td style={{ color: "var(--text-muted)" }}>{trace.errorMessage || trace.errorCode || "-"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                {sample.buildErrors && sample.buildErrors.length > 0 && (
                  <div className={styles.traceBuildErrorBlock}>
                    <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "#fca5a5", marginBottom: 6 }}>Canonical Build Errors</div>
                    {sample.buildErrors.map((err, ei) => (
                      <div key={ei} style={{ fontSize: 12, marginTop: 4 }}>
                        <strong>{err.field || "-"}</strong> · {err.errorCode} · {err.reason}
                      </div>
                    ))}
                  </div>
                )}
              </>
            );
          })()}
        </div>
      </div>
    )}
    ```

    **Part H — Add validation suggestions to existing issues list:**

    In the issues list section (lines 674–688), add a suggestion line after each issue message. Replace the existing `.issueText` span with a div containing the message and a suggestion:

    ```tsx
    <div key={`${issue.type}-${issue.message}`} className={styles.issueRow}>
      <div>
        <span className={styles.issueText}>{issue.message}</span>
        <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 4 }}>
          {getValidationSuggestion(issue.type.split("_")[0], issue.message.split(":")[0])}
        </div>
      </div>
      <span className={styles.issueCount}>{issue.affectedRows != null ? `${issue.affectedRows} rows` : issue.severity}</span>
    </div>
    ```

    This provides actionable guidance for each issue, e.g. "Source field does not exist in sample data. Re-map this target to an existing partner field."

    **Per D-02** (preserve existing layout): All new sections are inserted between existing sections — the existing validation banner, metric pills, field results table, preview rows, and issues list remain in place.
  </action>
  <verify>
    <automated>
      npx tsc --noEmit --strict frontend-next/src/components/review-center/guided-review-modal.tsx 2>&1 | head -30
    </automated>
  </verify>
  <done>
    - Step 3 shows progress bar with green/red segments and legend counts
    - Step 3 shows freshness section with staleness badge and version info
    - Step 3 shows trace gallery with before/after columns per sample row
    - Clicking 🔍 opens trace detail overlay with 7-column field-level trace table
    - Validation issues show human-readable suggestions
    - TypeScript compilation passes
    - Existing validation banner, metric pills, field results, preview rows, and issues list remain intact
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client→API | Runtime validation gate details come from API response (untrusted) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-260622-grp-01 | T | traceSamples data parsing | mitigate | All traceSamples fields are coerced to expected types via `String()`, `Number()`, `Boolean()` in normalizeRuntimeValidation; null/undefined handled with fallback values. No `any` pass-through. |
| T-260622-grp-02 | I | Validation suggestion template injection | mitigate | `getValidationSuggestion` uses `.replace()` on a fixed set of keys; the `field` parameter is constrained to the `{field}` placeholder only, not arbitrary string interpolation. No user data is injected unsafely. |
</threat_model>

<verification>
- Task 1: `npx tsc --noEmit` passes for lib/review-runtime.ts, types/review-center.ts, lib/api/review-center.ts
- Task 2: `npx tsc --noEmit` passes for guided-review-modal.tsx and review-center.module.css compiles
- No console errors in Step 3 after re-render
</verification>

<success_criteria>
1. `lib/review-runtime.ts` exists with all 5 helper functions, compiles cleanly
2. `types/review-center.ts` has `RuntimeFieldTrace`, `RuntimeTraceSample`, and `traceSamples` field
3. `lib/api/review-center.ts` passes through normalized `traceSamples` in `normalizeRuntimeValidation`
4. Step 3 renders progress bar with pass/fail percentages (when runtimeGate exists with details)
5. Step 3 renders freshness section showing staleness/version info
6. Step 3 renders trace gallery with before/after columns for each sample
7. Clicking the detail button (🔍) opens the trace detail overlay with 7-column field-level table
8. Validation issues display suggestion text beneath each issue message
9. Passing `npm run lint` (or equivalent) with no new errors on changed files

**Rollback plan:** If compilation fails, revert the changed files with `git checkout -- <file>` and fix type errors before retrying.
</success_criteria>

<output>
After completion, create `.planning/quick/260622-grp-migrate-review-runtime-t-legacy-frontend/260622-grp-01-SUMMARY.md`
</output>
