---
phase: 18-copilot-brief-3-step-modal
reviewed: 2026-06-09T12:00:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - src/services/copilot_context.py
  - frontend/app.js
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 18: Copilot Brief 3-Step Modal — Code Review Report

**Reviewed:** 2026-06-09T12:00:00Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Reviewed the backend (`src/services/copilot_context.py`) and frontend (`frontend/app.js`) changes for Phase 18. The backend correctly separates `decisionActions` from `secondaryActions`, adds the `step` field, and maintains backward compatibility via the existing `actions`/`recommendedAction` keys. The frontend correctly consumes `copilot.decisionActions` for rendering the Decision-step buttons instead of filtering `secondaryActions` by hardcoded keys.

One warning was found: the copilot-action post-execution handler in `bindViewActions` still uses a hardcoded array of decision action keys (`["reject_proposal", "approve_activate_next_runtime", "approve_keep_current"]`) to determine whether to close the brief after an action. This duplicates backend knowledge and will break silently if new decision actions are added on the backend without a frontend update. Two info-level items note that the backend's `step` field is unused by the frontend, and the step-determination logic duplicates conditions already evaluated in `_actions()`.

## Warnings

### WR-01: Hardcoded decision action keys in post-execution handler

**File:** `frontend/app.js:2679`
**Issue:** The `copilot-action` success handler in `bindViewActions` (line 2679) hardcodes `["reject_proposal", "approve_activate_next_runtime", "approve_keep_current"]` to decide whether closing the brief and showing a specific toast message is needed after a copilot action completes. This duplicates the backend's definition of "decision actions."

While the *rendering* of decision buttons correctly uses `copilot.decisionActions` from the backend (lines 654, 753–763), the *post-execution behavior* still relies on a hardcoded list. If the backend adds a new decision action key, the frontend will not close the brief after executing it — instead, it falls through to the generic toast at line 2685. This is a silent behavioral divergence, not a crash.

**Fix:** Instead of a hardcoded list, the frontend should check whether the executed action key exists in `state.copilotContext.decisionActions`. If it does, close the brief and use a decision-specific toast. If it doesn't, show the generic action-completed toast.

```javascript
// Replace lines 2679-2686:
const isDecisionAction = state.copilotContext?.decisionActions?.some(
  a => a.key === actionKey
);
if (isDecisionAction) {
  state.briefOpen = false;
  briefStep = 0;
  showToast(actionKey === "reject_proposal" ? "Proposal rejected." : "Proposal approved.");
} else {
  showToast(actionKey === "refresh_context" ? "Recommendation refreshed." : "Copilot action completed.");
}
```

## Info

### IN-01: Backend `step` field not consumed by frontend

**File:** `frontend/app.js:640-662`
**Issue:** The backend `step` field (lines 175–180 in `copilot_context.py`) was added specifically for the 3-step brief flow, but `renderCopilotBrief` never reads `copilot.step`. The frontend manages its own `briefStep` state and always starts at step 0 ("Brief"), regardless of whether the backend determined the user should be at "review" or "decision" step.

For example, when `has_packet` is true and `decision_actions` is non-empty, the backend sets `step = "decision"`, but the frontend still opens the modal on the "Brief" pane. The user must click "Next" twice to reach the decision buttons. Auto-advancing `briefStep` based on `copilot.step` would be a better UX and is what the field was designed for.

**Fix:** In `renderCopilotBrief` (or the `open-copilot-brief` handler at line 2996), set `briefStep` based on `copilot.step`:

```javascript
// In open-copilot-brief handler (~line 2997):
state.briefOpen = true;
briefStep = copilot.step === "decision" ? 2 : copilot.step === "review" ? 1 : 0;
render();
```

This auto-advances the modal to the relevant pane when the brief is opened.

### IN-02: `step` determination duplicates `_actions()` conditions

**File:** `src/services/copilot_context.py:175-180`
**Issue:** The `step` field computation (lines 175–180) re-evaluates the same conditions (`has_packet`, `has_draft`, `status`) that were already evaluated inside `_actions()`. This creates a subtle coupling — if the logic inside `_actions()` changes (e.g., what constitutes an actionable decision), the `step` logic could diverge silently.

The decision about whether the `step` should be "decision" vs "review" is already decided inside `_actions()` by whether it populates the `decision` list. Returning the step directly from `_actions()` would eliminate the duplicate branching.

**Fix:** Add the step value to `_actions()`'s return or have `_actions()` return the step alongside its current outputs, rather than re-deriving it:

```python
# Option A: Let _actions() return the intended step
def _actions(self, ...) -> tuple[Optional[dict], list[dict], list[dict], str]:
    ...
    if status == "healthy":
        return None, secondary, decision, "brief"
    if has_packet or has_draft:
        step = "decision" if decision else "review"
        return primary, secondary, decision, step
    return primary, secondary, decision, "brief"

# Then in resolve():
primary_action, secondary_actions, decision_actions, step = self._actions(...)
```

This ensures the step is always consistent with what `_actions()` actually returned.

---

_Reviewed: 2026-06-09T12:00:00Z_
_Reviewer: OpenCode (gsd-code-reviewer)_
_Depth: standard_
