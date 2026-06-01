---
phase: "11"
plan: "11-03"
subsystem: "ai-analysis"
tags:
  - "fastapi"
  - "uvicorn"
  - "api-endpoints"
  - "daily-report"
  - "threshold-alerts"
  - "pydantic"
dependency_graph:
  requires:
    - phase: "11-02"
      provides: "insights.py orchestration, services.py helpers, prompts, LLM providers"
    - phase: "11-01"
      provides: "AnalysisConfig, schemas, MetricsService, GroupingEngine"
  provides:
    - "FastAPI app with lifespan MongoDB management"
    - "GET /api/v1/insights/summary endpoint"
    - "GET /api/v1/insights/discrepancies endpoint"
    - "GET /api/v1/reports/daily endpoint"
    - "run.py serve subcommand (uvicorn on port 8000)"
    - "DailyReporter (format only, no computation)"
    - "ThresholdAlerter (check only, no computation)"
    - "Request validation and error handling"
  affects:
    - "run.py (serve subcommand added)"
    - "pyproject.toml (fastapi, uvicorn added)"
tech-stack:
  added:
    - "fastapi>=0.115.0"
    - "uvicorn[standard]>=0.30.0"
  patterns:
    - "FastAPI lifespan for connection management"
    - "Lazy imports inside endpoint functions"
    - "TestClient + mock orchestration for API testing"
    - "Reporter/alerter delegate to MetricsService (single source of truth)"
    - "Threshold severity scaling based on breach ratio"
key-files:
  created:
    - "src/api/__init__.py"
    - "src/api/insights.py"
    - "src/analysis/reporter.py"
    - "src/analysis/alerter.py"
    - "tests/test_api_insights.py"
    - "tests/test_analysis_reporter.py"
    - "tests/test_analysis_alerter.py"
  modified:
    - "pyproject.toml"
    - "run.py"
key-decisions:
  - "Lazy imports inside endpoint functions to avoid circular dependencies"
  - "Date validation returns 400 (not 422) for missing dates — explicit validation"
  - "Reporter/alerter use AnalysisConfig defaults when no config provided"
  - "Alert severity scales by ratio: >4x=critical, >2x=high, >1.5x=medium, else=low"
  - "Failed partners skipped during report generation (graceful degradation)"
requirements-completed:
  - "AI-ANALYSIS-03"
metrics:
  duration: "~30 min"
  completed: "2026-06-01"
  tasks_completed: 2
  tasks_total: 2
  tests_added: 44
  tests_passed: 44
---

# Phase 11 Plan 03: API & Reports Summary

**FastAPI API layer with 3 insight endpoints, daily batch report generation, and threshold-based alerts — all delegating to MetricsService as single source of truth.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-06-01T04:30:00Z
- **Completed:** 2026-06-01T05:00:00Z
- **Tasks:** 2
- **Files modified:** 9 (7 source + 3 test + 2 config)

## Accomplishments

- FastAPI app with lifespan MongoDB connection management
- 3 API endpoints: summary, discrepancies, daily report
- `run.py serve` subcommand for uvicorn server (port 8000)
- Request validation (date format, partner required, focus type)
- Error handling (400/500 JSON responses)
- DailyReporter: format-only report generation using insights.get_summary()
- ThresholdAlerter: check-only threshold breach detection
- Alert severity scaling based on breach ratio
- 44 unit tests across API, reporter, and alerter

## Task Commits

Each task was committed atomically:

1. **Task 3.1: FastAPI Insights Endpoints** - `9cd7bb0` (feat)
2. **Task 3.2: Daily Batch Report + Threshold Alerts** - `1c14937` (feat)
3. **Chore: reports/ to .gitignore** - `0410af2` (chore)

## Files Created/Modified

- `src/api/__init__.py` - FastAPI app factory with lifespan MongoDB management
- `src/api/insights.py` - 3 endpoints: summary, discrepancies, daily report with validation
- `src/analysis/reporter.py` - DailyReporter: generate_report(), save_report() — format only
- `src/analysis/alerter.py` - ThresholdAlerter: check_thresholds(), alerts_for_report() — check only
- `tests/test_api_insights.py` - 18 tests for API endpoints and validation helpers
- `tests/test_analysis_reporter.py` - 8 tests for DailyReporter
- `tests/test_analysis_alerter.py` - 18 tests for ThresholdAlerter
- `pyproject.toml` - Added fastapi>=0.115.0, uvicorn[standard]>=0.30.0
- `run.py` - Added `serve` subcommand for uvicorn server

## Decisions Made

1. **Lazy imports inside endpoints:** `get_summary`, `get_discrepancies`, `DailyReporter`, `ThresholdAlerter` are imported inside endpoint functions to avoid circular import issues and allow clean mocking in tests.
2. **Date validation returns 400:** Missing/invalid dates return HTTP 400 with explicit error message rather than FastAPI's default 422 — clearer API contract.
3. **Graceful partner skipping:** DailyReporter skips partners that fail during summary generation rather than failing the entire report — ensures partial reports are still useful.
4. **Alert severity by breach ratio:** Severity scales based on how much the value exceeds the threshold (>4x=critical, >2x=high, >1.5x=medium) — provides meaningful differentiation.
5. **No duplicate computation:** Both DailyReporter and ThresholdAlerter read from MetricsService/insights output — they format and check only, never compute metrics themselves.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all implemented components are fully functional. The `generated_at` field in reports is replaced with proper ISO timestamps by the API layer (as designed).

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag:information_disclosure | `src/api/insights.py` | API endpoints are read-only (GET) — no mutation risk (T-11-05 mitigation verified) |
| threat_flag:information_disclosure | `src/analysis/reporter.py` | Report files contain only aggregated data, no raw transactions (T-11-07 mitigation verified) |
| threat_flag:denial_of_service | `src/api/insights.py` | LLM calls have timeout from AnalysisConfig — async endpoints don't block (T-11-04 mitigation) |

## Self-Check: PASSED

All created files verified:
- `src/api/__init__.py` ✓
- `src/api/insights.py` ✓
- `src/analysis/reporter.py` ✓
- `src/analysis/alerter.py` ✓
- `tests/test_api_insights.py` ✓
- `tests/test_analysis_reporter.py` ✓
- `tests/test_analysis_alerter.py` ✓

All commits verified:
- `9cd7bb0` ✓
- `1c14937` ✓
- `0410af2` ✓

All 166 analysis+API tests pass (59 Wave 1 + 63 Wave 2 + 44 Wave 3).
