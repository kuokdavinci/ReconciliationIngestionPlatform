# PostgreSQL Migration Plan

## Objective
Migrate the ingestion and reconciliation data layer from MongoDB to PostgreSQL to resolve bulk insert bottlenecks and CPU-heavy Python in-memory joins.

## Proposed Architecture
1. **Database Schema**:
   - `partner_transaction`: Raw partner rows imported from files.
   - `internal_transaction`: Internal core transaction rows.
   - `reconciliation_result`: Matching results.
2. **Optimized Ingestion Flow**:
   - Parse files using `python-calamine` into tuples.
   - Batch import into `partner_transaction` using PostgreSQL `COPY` command via `asyncpg` (`copy_records_to_table`), bypassing standard SQL parsers.
3. **Database-level Reconciliation**:
   - Instead of Python-in-memory matching loop, execute a single SQL `INSERT ... SELECT ... LEFT JOIN` query with conditional `CASE WHEN` to perform matching and record results directly.

## Action Items
- [ ] Setup PostgreSQL Docker service in `docker-compose.yml`.
- [ ] Define SQLAlchemy / SQL schemas for transactional tables.
- [ ] Re-implement repositories (`DataContainerRepository`, `InternalTransactionRepository`, and `ReconciliationResultRepository`) using SQL / asyncpg.
- [ ] Migrate `IngestionPipeline` to use `asyncpg` bulk `COPY`.
- [ ] Migrate `ReconciliationEngine` to perform SQL join-based matching instead of Python-in-memory matching.
- [ ] Update testing suite to spin up test PostgreSQL databases.

