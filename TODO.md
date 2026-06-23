# Target: Review Center Remaining Hardening

## Objective

Finish the remaining Review Center hardening after the component split.

The UI step components already exist. Do not split UI again unless strictly necessary. Focus only on:

1. extracting repeated packet loading logic
2. moving modal orchestration into hooks
3. centralizing actor handling
4. making backend API URL configurable
5. fixing stale docs

Do not add new product features.

---

## Current State

The Review Center has already been partially refactored:

```text
frontend-next/src/components/review-center/guided-review-scope-step.tsx
frontend-next/src/components/review-center/guided-review-mapping-step.tsx
frontend-next/src/components/review-center/guided-review-validation-step.tsx
frontend-next/src/components/review-center/guided-review-decision-step.tsx
```

Keep these files. Do not rewrite them unless needed for props cleanup.

The remaining problem is not UI structure. The remaining problem is orchestration and drift.

---

## Scope

Work only on:

```text
frontend-next/src/app/review-center/page.tsx
frontend-next/src/components/review-center/guided-review-modal.tsx
frontend-next/src/components/review-center/guided-review-*.tsx
frontend-next/src/lib/api/client.ts
frontend-next/src/lib/api/review-center.ts
frontend-next/src/lib/actor.ts
frontend-next/src/components/actor-selector.tsx
frontend-next/next.config.ts
.env.example
README.md
docs/ARCHITECTURE.md
```

Avoid backend changes unless the frontend cannot preserve current behavior.

---

# Phase 1 — Extract Review Packet Loading

## Problem

`review-center/page.tsx` duplicates logic for:

* loading packets
* filtering pending packets
* sorting by `createdAt`
* selecting requested packet from URL
* keeping current selected packet
* falling back to newest packet

This logic appears in both `refreshPackets` and `bootstrapPackets`.

## Required Change

Create:

```text
frontend-next/src/components/review-center/use-review-packets.ts
```

## Required Helpers

Implement:

```ts
import type { ReviewPacket } from "@/types/review-center";

export function getPendingPackets(packets: ReviewPacket[]): ReviewPacket[] {
  return [...packets]
    .filter((packet) => String(packet.status).toUpperCase() === "PENDING")
    .sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
}

export function selectReviewPacketId({
  packets,
  currentId,
  requestedId,
}: {
  packets: ReviewPacket[];
  currentId?: string | null;
  requestedId?: string | null;
}): string | null {
  if (requestedId && packets.some((packet) => packet._id === requestedId)) {
    return requestedId;
  }

  if (currentId && packets.some((packet) => packet._id === currentId)) {
    return currentId;
  }

  return packets[0]?._id ?? null;
}
```

## Hook API

Implement:

```ts
export function useReviewPackets(requestedId?: string | null) {
  return {
    packets,
    selectedId,
    selectedPacket,
    loading,
    setSelectedId,
    refreshPackets,
  };
}
```

The hook must:

* call `api.listReviewPackets()`
* filter only `PENDING`
* sort newest first
* keep selected packet when possible
* use requested packet from URL when valid
* fetch selected packet detail with `api.getReviewPacket`
* expose `refreshPackets`

## Update Page

After this phase, `page.tsx` should mainly render layout.

Expected shape:

```ts
const requestedId = searchParams.get("packet");
const {
  packets,
  selectedId,
  selectedPacket,
  loading,
  setSelectedId,
  refreshPackets,
} = useReviewPackets(requestedId);
```

Do not keep duplicated packet selection logic inside `page.tsx`.

---

# Phase 2 — Extract Guided Review Orchestration

## Problem

`guided-review-modal.tsx` has already split UI steps, but it still owns too much orchestration:

* local packet state
* scope classification loading
* AI mapping loading
* mapping save
* runtime validation
* approve/reject
* post-approval polling
* validation state derivation
* mapping grouping
* trace sample state

Do not split UI again. Move orchestration into hooks.

## Required Files

Create:

```text
frontend-next/src/components/review-center/use-guided-review.ts
frontend-next/src/components/review-center/use-post-approval-polling.ts
```

## use-guided-review Responsibilities

`use-guided-review.ts` should own:

* `localPacket`
* `selectedScope`
* `scopeClassification`
* `aiMapping`
* `fieldMappings`
* loading flags
* error strings
* `handleContinueFromScope`
* `handleMappingChange`
* `handleSaveMapping`
* `handleValidateRuntime`
* `handleApproveActivate`
* `handleReject`
* derived mapping groups:

  * `sourceBackedMappings`
  * `constantMappings`
  * `constantFieldEntries`
  * `displayFieldResults`
* derived validation state

Suggested API:

```ts
export function useGuidedReview({
  packet,
  open,
  onRefresh,
  onClose,
}: {
  packet: ReviewPacket | null;
  open: boolean;
  onRefresh: () => void;
  onClose: () => void;
}) {
  return {
    localPacket,
    selectedScope,
    setSelectedScope,
    step,
    setStep,

    scopeClassification,
    scopeLoading,
    scopeError,
    isSavingScope,

    aiMapping,
    aiMappingLoading,
    aiMappingError,
    fieldMappings,
    sourceBackedMappings,
    constantMappings,
    isSavingMapping,

    validationState,
    runtimeValidationState,
    displayFieldResults,
    summary,
    topIssues,
    sigHeaders,
    isValidatingRuntime,

    isSubmitting,
    postApprovalRun,
    setPostApprovalRun,

    handleClose,
    handleContinueFromScope,
    handleMappingChange,
    handleSaveMapping,
    handleValidateRuntime,
    handleApproveActivate,
    handleReject,
    retryScopeClassification,
  };
}
```

Keep the existing behavior. This is a refactor, not a redesign.

## use-post-approval-polling Responsibilities

Move polling logic out of the modal.

```ts
export function usePostApprovalPolling({
  packetId,
  enabled,
  onCompleted,
}: {
  packetId?: string | null;
  enabled: boolean;
  onCompleted?: () => void;
}) {
  return {
    run,
    setRun,
    loading,
    error,
    startPolling,
    stopPolling,
  };
}
```

Rules:

* Poll every 1500–2000ms.
* Stop when status is `COMPLETED` or `FAILED`.
* Cleanup interval on unmount.
* Do not start duplicate intervals.
* Do not swallow terminal failure silently.

## Update GuidedReviewModal

After this phase, `guided-review-modal.tsx` should only own:

* dialog shell
* step rail
* rendering step components
* passing hook state/actions to step components

Target:

```text
guided-review-modal.tsx should be around 180–260 lines.
```

Do not force this if it makes code worse, but it should no longer contain all action orchestration.

---

# Phase 3 — Centralize Actor Handling

## Problem

Actor is currently read directly inside API client and falls back to `"Administrator"`. Some Review Center actions also pass `"Administrator"` manually.

This should be centralized.

## Create

```text
frontend-next/src/lib/actor.ts
```

## Required API

```ts
const ACTOR_STORAGE_KEY = "actor";
const DEFAULT_ACTOR = "Administrator";

export function getCurrentActor(): string {
  if (typeof window === "undefined") return DEFAULT_ACTOR;

  try {
    const stored = window.sessionStorage.getItem(ACTOR_STORAGE_KEY);
    return stored?.trim() || DEFAULT_ACTOR;
  } catch {
    return DEFAULT_ACTOR;
  }
}

export function setCurrentActor(actor: string): void {
  if (typeof window === "undefined") return;

  const normalized = actor.trim() || DEFAULT_ACTOR;
  window.sessionStorage.setItem(ACTOR_STORAGE_KEY, normalized);
}
```

## Update API Client

Update:

```text
frontend-next/src/lib/api/client.ts
```

Replace local `getActor()` with:

```ts
import { getCurrentActor } from "@/lib/actor";
```

Then:

```ts
function actorHeaders(): Record<string, string> {
  return { "X-Actor": getCurrentActor() };
}
```

## Update Review Actions

In guided review approval/reject actions, do not pass hard-coded `"Administrator"`.

Use:

```ts
import { getCurrentActor } from "@/lib/actor";
```

Then:

```ts
await api.approveActivate(packetId, getCurrentActor(), selectedScope);
await api.rejectPacket(packetId, getCurrentActor());
```

## Optional UI

Create a very small component:

```text
frontend-next/src/components/actor-selector.tsx
```

It can be placed in Review Center top area or skipped if too much UI churn.

The important part is centralizing the source of truth, not adding auth.

---

# Phase 4 — Backend API URL Config

## Problem

`frontend-next/next.config.ts` hard-codes:

```text
http://localhost:8000
```

## Required Change

Update:

```text
frontend-next/next.config.ts
```

Use:

```ts
import type { NextConfig } from "next";

const backendApiUrl = process.env.BACKEND_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
```

## Update Env Example

Update:

```text
.env.example
```

Add:

```env
BACKEND_API_URL=http://localhost:8000
```

If `frontend-next/.env.example` exists, add the same value there too.

---

# Phase 5 — Docs Cleanup

## README

Fix Quick Start:

Current target should be:

```bash
npm --prefix frontend-next install
npm --prefix frontend-next run dev
```

Do not leave plain:

```bash
npm run dev
```

unless the README explicitly says to run it inside `frontend-next`.

## README Dashboard Section

Replace legacy wording with:

```md
## Dashboard

`frontend-next/` is the active dashboard, built with Next.js and TypeScript.

Main active UI paths:

- `frontend-next/src/app/review-center/`
- `frontend-next/src/components/review-center/`
- `frontend-next/src/lib/api/review-center.ts`

The old `frontend/` Vite dashboard is kept only as a legacy/reference implementation.
```

## Documentation Contract

Replace references to `frontend/app.js` as the active dashboard source.

Use:

```md
- dashboard route descriptions must match `frontend-next/src/app/` and active Review Center components
```

## Architecture Doc

Update:

```text
docs/ARCHITECTURE.md
```

Change Main Runtime Pieces from `frontend/` to `frontend-next/`.

Use:

```md
- `frontend-next/`
  - Active Next.js + TypeScript dashboard that communicates with FastAPI through `/api`
- `frontend/`
  - Legacy Vite dashboard retained as reference only
```

Replace the old “Frontend Shape” section with:

```md
## Frontend Shape

The active dashboard is `frontend-next/`.

Main active views:

- Review Center
- Reconciliation
- Mapping Studio
- Automation

Review Center owns the operator approval workflow:

1. Load pending review packets.
2. Confirm file scope.
3. Review or adjust draft mapping.
4. Run runtime validation.
5. Approve/reject.
6. Track post-approval ingestion and reconciliation progress.

The old `frontend/` directory is legacy/reference only.
```

---

# Phase 6 — Cleanup Small Lint Issues

Search and clean:

```bash
grep -R "Administrator" frontend-next/src -n
grep -R "frontend/app.js" README.md docs -n
grep -R "http://localhost:8000" frontend-next .env.example README.md docs -n
```

Expected:

* `"Administrator"` should only exist in `frontend-next/src/lib/actor.ts`.
* `frontend/app.js` should not be described as active dashboard.
* `http://localhost:8000` is allowed only as env fallback/example.

Also remove unused imports, especially in step components.

---

# Acceptance Criteria

The task is done when:

1. `review-center/page.tsx` no longer duplicates packet loading/selection logic.
2. `guided-review-modal.tsx` no longer owns polling/action orchestration directly.
3. Step UI components remain intact.
4. Actor fallback is centralized in `frontend-next/src/lib/actor.ts`.
5. No Review Center action hard-codes `"Administrator"`.
6. `next.config.ts` uses `BACKEND_API_URL` with local fallback.
7. `.env.example` includes `BACKEND_API_URL`.
8. README Quick Start runs frontend correctly.
9. README and Architecture docs describe `frontend-next` as active and `frontend/` as legacy.
10. Lint and focused backend tests are run.

---

# Required Checks

Run:

```bash
npm --prefix frontend-next run lint
uv run python -m pytest tests/test_api_review_packets.py -v
```

Optional if not too slow:

```bash
uv run python -m pytest -v
```

---

# Final Report Format

After implementation, report:

```md
## Summary

- Extracted Review Center packet loading into ...
- Moved guided review orchestration into ...
- Centralized actor handling in ...
- Made backend API URL configurable via ...
- Updated README and architecture docs ...

## Tests

- `npm --prefix frontend-next run lint`: pass/fail
- `uv run python -m pytest tests/test_api_review_packets.py -v`: pass/fail
- `uv run python -m pytest -v`: pass/fail/not run

## Notes

- Mention any pre-existing failures.
- Mention any behavior intentionally preserved.
```
