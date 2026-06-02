# Phase 14: AI Analysis Domain Standardization — Design Context

## Overview

Phase 14 is a **quality & production-hardening** phase for the AI Analysis Layer (Phase 11). The module was implemented with 166+ tests and 3 waves (foundation → insight engine → API/reports), but scored **14/100** in AI Evaluation review, revealing critical gaps in:

1. **Output guardrails & hallucination detection** — No verification that LLM-generated insights match input data
2. **Online guardrails** — No real-time checks before returning LLM output to users
3. **Quality degradation monitoring** — No baseline or drift detection
4. **Eval tooling** — No dedicated AI evaluation framework
5. **CI/CD integration** — No automated eval pipeline

Additionally, the Code Review found:
- **2 critical bugs** in `run.py` (undefined `sheet_name`, duplicate argparse `action`)
- **11 warnings** (unused params, redundant code, per-request LLM provider creation, hardcoded dates)
- **3 info-level issues** (import in function body, `generated_at` uses date string, duplicated test fixture)

## Scope

| Area | What | Source |
|------|------|--------|
| **AI Output Guardrails** | Cross-reference LLM claims against `AnalysisInput` data | EVAL-REVIEW |
| **Hallucination Detection** | Verify numeric claims, LLM-as-judge for unsupported insights | EVAL-REVIEW |
| **Online Guardrails** | Post-LLM validation before returning to API layer | EVAL-REVIEW |
| **Code Quality** | Fix critical bugs, warnings, info issues from code review | REVIEW.md |
| **Eval Infrastructure** | Reference dataset, eval tooling, CI/CD pipeline | EVAL-REVIEW |

## Out of Scope

- New AI insight categories or features
- New API endpoints beyond existing 3
- UI changes
- Infrastructure for production deployment (Docker, monitoring dashboard)
- ML anomaly detection (still deferred from Phase 11)

## Key Constraints

- **Backward compatibility**: All existing API contracts must remain unchanged
- **No new external dependencies** unless essential (eval tooling is optional)
- **Existing tests must continue to pass**: `pytest tests/test_analysis_*.py tests/test_api_insights.py -x` must still pass
- **Privacy**: No raw transaction data in guardrail/validation code either

## Success Criteria (from EVAL-REVIEW targets)

- Output validation guardrail cross-references numeric claims in insights against `AnalysisInput`
- Hallucination detection flags insights with unsupported numeric claims
- All critical and warning-level code review issues resolved
- LLM provider created once at application startup (not per-request)
- Reference dataset extracted from existing E2E scenarios into `tests/data/`
- All existing 166+ tests continue to pass
- No raw transaction data exposed in new code

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Guardrail approach | Code-based cross-reference + optional LLM-as-judge | Code-based is deterministic, LLM-as-judge catches semantic hallucinations |
| Guardrail location | `insights.py` post-LLM, before cache write | Catches all paths (API + reporter) |
| Reference dataset format | JSONL with `input`/`expected_output`/`focus` | Standard eval format, compatible with promptfoo |
| Eval tooling | promptfoo CLI (optional dependency) | Lightweight, easy to run, no platform lock-in |
| CI/CD | GitHub Actions workflow | Standard for Python projects, runs tests + eval |
