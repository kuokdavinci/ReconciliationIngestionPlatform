# Reconciliation Ingestion Platform - Roadmap

## Requirements

**Phase 1:** FOUND-01, FOUND-02, FOUND-03
**Phase 2:** READER-01, READER-02
**Phase 3:** CONFIG-01, CONFIG-02
**Phase 4:** NORM-01, NORM-02
**Phase 5:** VALID-01, VALID-02
**Phase 6:** PERSIST-01, PERSIST-02
**Phase 7:** LOG-01, LOG-02
**Phase 8:** RECON-01, RECON-02, RECON-03, RECON-04
**Phase 9:** COMP-01, COMP-02, COMP-03, COMP-04
**Phase 10:** REPORT-01, REPORT-02, REPORT-03, REPORT-04
**Phase 11:** AI-ANALYSIS-01, AI-ANALYSIS-02, AI-ANALYSIS-03
**Phase 12:** DATA-API-01, DATA-API-02
**Phase 13:** BACKEND-AUDIT-01, UI-POLISH-01, DATA-FLOW-01
**Phase 14:** AI-DOMAIN-01, AI-DOMAIN-02, AI-DOMAIN-03
**Phase 15:** UI-DATA-01, UI-DATA-02, UI-DATA-03, UI-DATA-04, UI-DATA-05

---

## Phase 1: Foundation

**Goal:** Project skeleton, database models, core type definitions, and configuration structure

**Requirements:**
- FOUND-01: Project structure with Python package layout, dependencies (openpyxl, pydantic, motor/pymongo, python-decouple)
- FOUND-02: MongoDB models for reconciliation_file, reconciliation_mapping_config, data_container
- FOUND-03: Core canonical transaction types and constants

**Plans:** 2 plans

Plans:
- [x] 01-01-PLAN.md — Project structure, core types, enums, constants, configuration
- [x] 01-02-PLAN.md — MongoDB models, repositories, indexes

---

## Phase 2: File Reader

**Goal:** Excel file reader with streaming support, sheet selection, and row filtering

**Requirements:**
- READER-01: Stream Excel rows efficiently using openpyxl read-only mode
- READER-02: Support configurable sheet selection, skip empty/summary rows

**Plans:** 2 plans

Plans:
- [x] 02-01-PLAN.md — Core Excel streaming reader with openpyxl read-only mode, sheet selection, start_row
- [x] 02-02-PLAN.md — Row filtering (empty/summary), MappingConfig integration, comprehensive tests

---

## Phase 3: Mapping Configuration

**Goal:** Dynamic mapping configuration engine that loads and interprets partner-specific parsing rules

**Requirements:**
- CONFIG-01: Mapping config loader from MongoDB (field mappings, transformations, status mappings, constants)
- CONFIG-02: Config versioning and caching

**Plans:** 2 plans

Plans:
- [x] 03-01-PLAN.md — ConfigCache (TTL in-memory) and ConfigValidator (field mapping integrity checks)
- [x] 03-02-PLAN.md — ConfigLoader service with repository, cache, validator integration + full test suite

---

## Phase 4: Normalization

**Goal:** Dynamic mapper that converts partner-specific fields into canonical transaction model

**Requirements:**
- NORM-01: Dynamic field mapping engine (column → canonical field, type conversion, constant values)
- NORM-02: Status normalization (partner-specific status → canonical SUCCESS/FAILED/etc.)

**Plans:** 2 plans

Plans:
- [x] 04-01-PLAN.md — Core TransactionNormalizer with STRING/DECIMAL/DATE/CONSTANT type conversion and error collection
- [x] 04-02-PLAN.md — MAPPING type status normalization, CanonicalTransaction builder, comprehensive tests

---

## Phase 5: Validation

**Goal:** Validation layer for normalized transactions

**Requirements:**
- VALID-01: Required field validation, decimal validation, date validation, status validation
- VALID-02: Duplicate detection (identify + reconciliationDate + trace, fileHash)

**Plans:** 2 plans

Plans:
- [x] 05-01-PLAN.md — Core Validator with required field, decimal, date, status validation rules and ValidationResult
- [x] 05-02-PLAN.md — Duplicate detection (transaction + file level), repository integration, comprehensive tests

---

## Phase 6: Persistence & Ingestion Pipeline

**Goal:** Database persistence layer and full ingestion pipeline orchestration

**Requirements:**
- PERSIST-01: Save normalized transactions to data_container, update reconciliation_file statistics
- PERSIST-02: Full ingestion pipeline orchestration (file → read → map → normalize → validate → persist)

**Plans:** 2 plans

Plans:
- [x] 06-01-PLAN.md — IngestionPipeline service with full orchestration, batch insertion, per-row error handling
- [x] 06-02-PLAN.md — Integration test fixtures, realistic test data, comprehensive pipeline scenario tests

---

## Phase 7: Logging & Tracking

**Goal:** Structured logging, file processing lifecycle tracking, and processing statistics

**Requirements:**
- LOG-01: Structured JSON logging (fileId, row, trace, status, reason)
- LOG-02: File processing lifecycle tracking (PROCESSING → COMPLETED/FAILED), statistics (total/success/failed rows)

**Plans:** 2 plans

Plans:
- [x] 07-01-PLAN.md — Structured JSON logger with formatters, event types, per-row/file emit helpers
- [x] 07-02-PLAN.md — Integrate logger into IngestionPipeline, lifecycle events, logging tests

---

## Phase 8: Reconciliation Engine

**Goal:** Match transactions between partner data and internal records, detect discrepancies, and store reconciliation results

**Requirements:**
- RECON-01: Fetch transactions from 2 sources (partner data_container + internal system)
- RECON-02: Match engine — match by trace, date range, amount tolerance
- RECON-03: Discrepancy detection — amount mismatch, status mismatch, missing transactions
- RECON-04: Result storage — matched/unmatched/discrepancy records with reason codes

**Plans:** 0 plans (planned — see FUTURE_PLAN.md)

---

## Phase 9: Compensation Workflow

**Goal:** Auto-create compensation transactions for identified discrepancies, with retry and escalation support

**Requirements:**
- COMP-01: Compensation rule engine — define rules for each discrepancy type
- COMP-02: Auto-generate compensation transactions (adjustment entries)
- COMP-03: Retry orchestration — retry failed compensations with exponential backoff
- COMP-04: Escalation — flag unresolved discrepancies after N retries

**Plans:** 0 plans (planned — see FUTURE_PLAN.md)

---

## Phase 10: Dashboard & Reporting

**Goal:** Provide visibility into ingestion, reconciliation, and compensation status via reports and API endpoints

**Requirements:**
- REPORT-01: Ingestion summary — files processed, success/failure rates, duration
- REPORT-02: Reconciliation summary — match rates, discrepancy breakdown by type
- REPORT-03: Compensation summary — success rates, pending/escalated counts
- REPORT-04: Partner onboarding report — config validation, test file processing

**Plans:** 0 plans (planned — see FUTURE_PLAN.md)

---

## Phase 11: AI Analysis Layer

**Goal:** Intelligent analysis layer that reads reconciliation results, uses LLM + rule-based grouping to generate actionable insights for operators (performance issues, partner behavior trends, data inconsistency patterns).

**Requirements:**
- AI-ANALYSIS-01: LLM-powered insight engine — explain mismatches, detect operational issues, generate natural language summaries from `reconciliation_result` data
- AI-ANALYSIS-02: Rule-based grouping — cluster reconciliation results by status, partner, amount range for structured reporting
- AI-ANALYSIS-03: API & report output — expose insights via API response, daily batch report, optional threshold-based alerts

**Plans:** 3/1 plans complete

Plans:
- [x] 11-01-PLAN.md — Foundation: LLM provider abstraction, rule-based grouping, aggregated metrics (Wave 1)
- [x] 11-02-PLAN.md — Insight engine: prompt templates, 3 insight generators, orchestrator (Wave 2)
- [x] 11-03-PLAN.md — API & reports: FastAPI endpoints, daily batch report, threshold alerts (Wave 3)

---

## Phase 12: Reconciliation & Data Explorer API

**Goal:** Thin read-only FastAPI endpoints for querying reconciliation results (`reconciliation_result`) and browsing raw transaction data (`data_container`, `reconciliation_file`), providing operators with direct API access to complement AI-powered insights.

**Requirements:**
- DATA-API-01: Reconciliation API — query, filter, and aggregate reconciliation results by partner/date/status
- DATA-API-02: Data Explorer API — browse DataContainer transactions and ReconciliationFile records with pagination and filtering

**Plans:** 1/1 plans complete

Plans:
- [x] 12-01-PLAN.md — Reconciliation API + Data Explorer API: endpoints, repository extensions, app registration, tests

---

## Phase 13: Backend Audit & UI Polish

**Goal:** Audit backend correctness, refine UI to show core features (mapping usage list), and verify data flow ensures unmapped partner data is normalized before reconciliation.

**Requirements:**
- BACKEND-AUDIT-01: Backend correctness audit — verify all components (ingestion, normalization, reconciliation, AI analysis) produce correct results across edge cases
- UI-POLISH-01: UI refinement — display mapping configuration usage list and other core feature data in the dashboard
- DATA-FLOW-01: Data flow verification — ensure unmapped partner data is properly normalized/rejected before entering reconciliation pipeline

**Plans:** 3/3 plans complete

Plans:
- [x] 13-01-PLAN.md — Backend audit edge case tests + Data flow guard in ReconciliationEngine (Wave 1)
- [x] 13-02-PLAN.md — New GET /api/v1/mappings endpoint for mapping config data (Wave 1)
- [x] 13-03-PLAN.md — UI: Mapping Configs sidebar tab + Reconciliation health widget on Overview (Wave 2)

---

## Phase 14: AI Analysis Domain Standardization

**Goal:** Improve AI Analysis Layer maturity from 14/100 EVAL score to production domain standards. Fix code review critical bugs, implement output guardrails/hallucination detection, add evaluation infrastructure, and harden code quality.

**Requirements:**
- AI-DOMAIN-01: AI output guardrails — cross-reference LLM insight claims against input data, detect hallucinations, downgrade unsupported severity
- AI-DOMAIN-02: Code quality hardening — fix critical bugs, redundant code, unused parameters, per-request provider, test standardization
- AI-DOMAIN-03: Eval infrastructure — reference dataset (JSONL), evaluator test, Makefile targets, CI/CD eval pipeline

**Plans:** 3 plans

Plans:
- [ ] 14-01-PLAN.md — AI output guardrails + hallucination detection (Wave 1)
- [ ] 14-02-PLAN.md — Code quality fixes from code review (Wave 1)
- [ ] 14-03-PLAN.md — Eval infrastructure + reference dataset (Wave 1)

---

## Phase 15: UI/UX Polish & Data Explorer Enhancement

**Goal:** Polish UI consistency and usability across all dashboard views. Fix styling issues (dropdown/date-picker contrast), reorder Dashboard & Insight layout, enhance Data Explorer with real DB-like filtering capabilities, add color-coded status badges, improve heading hierarchy, and remove non-functional UI elements.

**Requirements:**
- UI-DATA-01: Data Explorer status badges — color-code reconciliation status values in transaction and file tables
- UI-DATA-02: Dropdown/date-picker styling — fix visual consistency and background contrast issues
- UI-DATA-03: Dashboard & Insight layout restructure — move partner selection below total metrics section, remove non-functional "Regenerate AI Analysis" button
- UI-DATA-04: Heading hierarchy improvement — increase heading sizes for Insight and Audit Log sections
- UI-DATA-05: Data Explorer advanced filtering — add status, trace ID, amount range, and date range filters for real DB-like querying

**Plans:** 3 plans

Plans:
- [ ] 15-01-PLAN.md — Data Explorer status colors + heading hierarchy fixes (Wave 1)
- [ ] 15-02-PLAN.md — Dashboard layout restructure + remove dead UI (Wave 2)
- [ ] 15-03-PLAN.md — Data Explorer advanced filters + dropdown/date-picker styling (Wave 3)

---

## Phase 16: Data Intake Screen Refactor & Copilot Decision Mode

**Goal:** Reduce information overload on the Data Intake screen by replacing scattered status cards with a clearer hierarchy, and refactoring the Copilot Panel into a compact decision assistant with exactly one primary action.

**Requirements:**
- UI-INTAKE-01: Replace scattered cards (Active Runtime Config, Needs Review Now, Incoming Files, Blocked Or Failed, Review Items) with Runtime Status, Latest File Status, Review Readiness hierarchy
- UI-INTAKE-02: Rename user-facing copy — "Blocked Or Failed" → "Latest File Status"/"File Processing Issues", "Needs Review Now" → "Review Readiness", avoid "blocked" language when approved runtime is available
- UI-INTAKE-03: Copilot Panel compact decision mode — show only status, riskLevel, headline, summary, 2-3 reasons, one primary action + optional secondary refresh
- UI-INTAKE-04: Move evidence, safe checks, raw runtime/draft/file details into collapsed sections
- UI-INTAKE-05: Map decision states (healthy, monitor, needs_review, blocked) with exact primary actions and headlines
- UI-INTAKE-06: Maintain backward compatibility — additive backend fields (summary, reasons, secondaryActions, safeChecks), legacy Mongo field names (proposalConfigId, targetConfigId) must not leak into UI

**Plans:** 3/3 plans complete

Plans:
- [x] 16-01-PLAN.md — Backend: Add compact Copilot context fields (summary, reasons, primaryAction, secondaryActions) — Wave 1
- [x] 16-02-PLAN.md — Frontend: Restructure Data Intake screen to 3-section hierarchy (Runtime Status, Latest File Status, Review Readiness) — Wave 1
- [x] 16-03-PLAN.md — Frontend: Compact Copilot Panel with collapsed evidence/safe checks — Wave 2

---

## Phase 17: Navigation Restructure + Data Intake Refactor

**Goal:** Restructure sidebar navigation (Mapping Studio → Tools sub-group, Review Queue → Review Center). Rewrite Data Intake landing with Partner Snapshot grid + minimal Selected Partner Summary card.

**Requirements:**
- UX-NAV-01: Reorder primary nav: Data Intake, Review Center, Reconciliation, Automation; add Tools sub-group with Mapping Studio
- UX-NAV-02: Rename "Review Queue" → "Review Center" everywhere
- UX-INTAKE-07: Partner Snapshot grid — partner name, overall status, latest file, file count, pending changes
- UX-INTAKE-08: Selected Partner Summary — compact card with 3 fact pills (runtime, latest file, review), copilot sentence, Open Brief button, Upload file utility
- UX-INTAKE-09: Remove evidence cards, safe checks, decision controls from dashboard

**Plans:** 3 plans

Plans:
- [x] phases-17-20-ux-refactor/17-01-PLAN.md — Navigation restructure (routes, sidebar, icons, Tools group)
- [x] phases-17-20-ux-refactor/17-02-PLAN.md — Data Intake: Partner Snapshot grid + Selected Partner Summary
- [x] phases-17-20-ux-refactor/17-03-PLAN.md — Backend intake API extensions

---

## Phase 18: Copilot Brief 3-Step Modal

**Goal:** Replace 4-step/5-step Copilot Brief with focused 3-step modal: Brief → Review → Decision. Approve/Reject/Keep only on Decision step. Modal closes and dashboard refreshes after decision.

**Requirements:**
- UX-BRIEF-01: 3-step flow — Brief (status + facts), Review (item summary or monitoring), Decision (primary CTA + optional approve/reject)
- UX-BRIEF-02: No approve/reject/keep before Decision step
- UX-BRIEF-03: No repeated Review Queue / Mapping Studio buttons across steps
- UX-BRIEF-04: One dominant primary CTA per step
- UX-BRIEF-05: After decision action, close modal, refresh dashboard, show toast
- UX-BRIEF-06: Backend returns 3-step compatible copilot context

**Plans:** 3 plans

Plans:
- [x] phases-17-20-ux-refactor/18-01-PLAN.md — Backend 3-step copilot context
- [x] phases-17-20-ux-refactor/18-02-PLAN.md — Frontend 3-step modal (Brief → Review → Decision)
- [x] phases-17-20-ux-refactor/18-03-PLAN.md — Confirmation, toast, dashboard refresh after decision

---

## Phase 19: Review Center + Mapping Studio

**Goal:** Rename Review Queue → Review Center. Build full Review Center workflow (validate, approve, reject, send-to-studio). Build Mapping Studio as a workspace (upload → AI → edit → validate → handoff). Bidirectional handoff between centers.

**Requirements:**
- UX-REVIEW-01: "Review Center" replaces "Review Queue" in all UI copy
- UX-REVIEW-02: Review Center supports validate, approve-activate, approve-keep, reject, send-to-studio
- UX-STUDIO-01: Mapping Studio 5-step flow — upload, AI suggest, manual edit, validate, handoff
- UX-STUDIO-02: Handoff from Studio creates review item in Review Center
- UX-STUDIO-03: Send-to-studio from Review Center pre-loads mapping config

**Plans:** 3 plans

Plans:
- [x] phases-17-20-ux-refactor/19-01-PLAN.md — Review Center rename + full workflow
- [x] phases-17-20-ux-refactor/19-02-PLAN.md — Mapping Studio workspace
- [x] phases-17-20-ux-refactor/19-03-PLAN.md — Handoff integration + bidirectional nav

---

## Phase 20: Reconciliation View + Contextual Copilot

**Goal:** Reconciliation view with tabs, filters, AI Insights. Contextual Copilot per screen. Auto-trigger reconciliation after Approve & activate.

**Requirements:**
- UX-RECON-01: Reconciliation tabs — All / Matched / Unmatched / Error
- UX-RECON-02: Filters — amount range, date range
- UX-RECON-03: AI Insights — Summary, Anomalies, Patterns, Recommendations tabs
- UX-COPILOT-01: Copilot context is contextual per screen (intake, review, reconciliation, automation)
- UX-RECON-04: Approve & activate triggers reconciliation automatically

**Plans:** 3 plans

Plans:
- [ ] phases-17-20-ux-refactor/20-01-PLAN.md — Reconciliation tabs, filters, AI Insights
- [ ] phases-17-20-ux-refactor/20-02-PLAN.md — Contextual Copilot per screen
- [ ] phases-17-20-ux-refactor/20-03-PLAN.md — Auto-trigger reconciliation after approval

---

*Full plan files in `phases-17-20-ux-refactor/`*


