---
phase: "11"
plan: "11-02"
subsystem: "ai-analysis"
tags:
  - "llm"
  - "prompt-engineering"
  - "orchestration"
  - "rule-based"
  - "fallback"
  - "pydantic"
dependency_graph:
  requires:
    - phase: "11-01"
      provides: "LLMProvider protocol, OpenAICompatProvider, AnalysisConfig, schemas, GroupingEngine, MetricsService"
  provides:
    - "Prompt templates (system + analysis)"
    - "Insight generator orchestration (get_summary, get_discrepancies, generate_insights)"
    - "Services helpers (build_analysis_input, parse_llm_insights, format_findings)"
    - "Rule-based pre-processing (operational/partner/inconsistency anomaly extraction)"
    - "LLM fallback mechanism (rule-based when LLM fails)"
  affects:
    - "Plan 03 (API + reports)"
tech-stack:
  added: []
  patterns:
    - "Orchestration layer pattern (insights.py) vs helpers pattern (services.py)"
    - "Rule-based pre-processing before LLM enrichment"
    - "Graceful fallback to rule-based on LLM failure"
    - "Structured logging with event types (ai_insight_*)"
    - "JSON response parsing with markdown code block extraction"
key-files:
  created:
    - "src/analysis/prompts.py"
    - "src/analysis/insights.py"
    - "src/analysis/services.py"
    - "tests/test_analysis_prompts.py"
    - "tests/test_analysis_insights.py"
    - "tests/test_analysis_services.py"
  modified: []
key-decisions:
  - "Services.py ordered before insights.py in implementation (2.3 before 2.2) since orchestration depends on helpers"
  - "Rule-based fallback generates AnalysisResult objects from aggregated data when LLM is unavailable"
  - "LLM response parser handles markdown code blocks and surrounding text for robustness"
  - "Severity scaling: critical >20%, high >10%, medium >5%, low <=5% mismatch rate"
  - "MongoDB query helper converts documents to SimpleNamespace objects for compatibility with MetricsService/GroupingEngine"
patterns-established:
  - "Orchestration helpers (services.py) are pure functions — no IO, no query, no orchestration"
  - "Orchestration layer (insights.py) owns all async/LLM/MongoDB coordination"
  - "Prompt templates are focus-aware (operational/partner/inconsistency) with deterministic JSON output"
requirements-completed: []
metrics:
  duration: "~20 min"
  completed: "2026-06-01"
  tasks_completed: 3
  tasks_total: 3
  tests_added: 63
  tests_passed: 63
---

# Phase 11 Plan 02: Insight Engine Summary

**LLM-powered insight engine with prompt templates, orchestration layer, and rule-based fallback for reconciliation analysis across operational/partner/inconsistency focus types.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-06-01T04:02:00Z
- **Completed:** 2026-06-01T04:22:00Z
- **Tasks:** 3
- **Files modified:** 6 (3 source + 3 test)

## Accomplishments

- Prompt templates: system prompt (role, constraints, JSON output) + analysis prompt (focus-aware, no raw data)
- Insight generator: `get_summary()`, `get_discrepancies()`, `generate_insights()` with MongoDB → Metrics → Grouping → LLM flow
- Services helpers: `build_analysis_input()`, `parse_llm_insights()`, `format_findings()`, `rule_based_pre_process()`
- Rule-based fallback: generates actionable insights from aggregated data when LLM fails
- 63 unit tests across all 3 modules (22 prompts + 25 services + 16 insights)

## Task Commits

Each task was committed atomically:

1. **Task 2.1: Prompt Templates** - `eff31f1` (feat)
2. **Task 2.3: Services Helpers** - `429bcbe` (feat)
3. **Task 2.2: Insight Generator** - `b562f01` (feat)

## Files Created/Modified

- `src/analysis/prompts.py` - System prompt + analysis prompt builder with focus-aware instructions
- `src/analysis/insights.py` - Orchestration layer: get_summary, get_discrepancies, generate_insights with LLM fallback
- `src/analysis/services.py` - Pure function helpers: build_analysis_input, parse_llm_insights, format_findings, rule-based pre-processing
- `tests/test_analysis_prompts.py` - 22 tests for prompt templates and formatting helpers
- `tests/test_analysis_services.py` - 25 tests for services helpers and rule-based pre-processing
- `tests/test_analysis_insights.py` - 16 tests for orchestration flow, LLM fallback, and edge cases

## Decisions Made

1. **Implementation order:** Task 2.3 (services) before Task 2.2 (insights) since orchestration depends on helper functions — follows actual code dependency, not plan numbering.
2. **Rule-based fallback severity scaling:** critical >20%, high >10%, medium >5%, low <=5% mismatch rate — provides meaningful severity even without LLM.
3. **LLM response parser robustness:** Handles direct JSON, markdown code blocks (```json ... ```), and JSON with surrounding text — defensive against varied LLM output formats.
4. **MongoDB query helper:** Converts documents to SimpleNamespace objects to maintain compatibility with existing MetricsService/GroupingEngine which expect object attributes.
5. **Structured logging:** All orchestration steps logged with event types (ai_insight_query, ai_insight_request, ai_insight_response, ai_insight_summary_complete, ai_insight_discrepancy_complete, ai_insight_llm_error) for observability.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None — all implemented components are fully functional. The `generated_at` field in `get_summary()` returns the date string (will be replaced by actual timestamp in the API layer — Wave 3).

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag:information_disclosure | `src/analysis/prompts.py` | Prompt templates only contain aggregated/grouped data — no raw transaction IDs or specific amounts (T-11-02 mitigation verified) |
| threat_flag:denial_of_service | `src/analysis/insights.py` | LLM calls have fallback to rule-based — system remains functional if LLM is unavailable (T-11-04 mitigation) |

## Self-Check: PASSED

All created files verified:
- `src/analysis/prompts.py` ✓
- `src/analysis/insights.py` ✓
- `src/analysis/services.py` ✓
- `tests/test_analysis_prompts.py` ✓
- `tests/test_analysis_insights.py` ✓
- `tests/test_analysis_services.py` ✓

All commits verified:
- `eff31f1` ✓
- `429bcbe` ✓
- `b562f01` ✓

All 122 analysis tests pass (59 Wave 1 + 63 Wave 2).
