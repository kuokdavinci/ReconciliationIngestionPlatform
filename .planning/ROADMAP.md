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

**Plans:** 1 plan

Plans:
- [ ] 12-01-PLAN.md — Reconciliation API + Data Explorer API: endpoints, repository extensions, app registration, tests

---

## Phase 13: Backend Audit & UI Polish

**Goal:** Audit backend correctness, refine UI to show core features (mapping usage list), and verify data flow ensures unmapped partner data is normalized before reconciliation.

**Requirements:**
- BACKEND-AUDIT-01: Backend correctness audit — verify all components (ingestion, normalization, reconciliation, AI analysis) produce correct results across edge cases
- UI-POLISH-01: UI refinement — display mapping configuration usage list and other core feature data in the dashboard
- DATA-FLOW-01: Data flow verification — ensure unmapped partner data is properly normalized/rejected before entering reconciliation pipeline

**Plans:** 0 plans
