# Full-Stream Review Mapping Design

**Goal:** Make Guided Review inspect the complete raw API stream while preserving one deterministic mapping gate and replaying exactly the raw pages that produced the packet.

## Approved architecture

Each fetched page keeps its `sourceUnitKey` (the stable page/cursor identity). The stream keeps its `rawStageKey` (the aggregate identity shared by all pages and Airflow retries). Mongo stores page metadata in `raw_ingestion_page`; the raw bytes remain in GridFS so BSON document size does not limit payloads.

The Review Packet stores the stream reference and bounded preview metadata. It does not copy large payloads into the packet. A packet-scoped API reads raw pages by `rawStageKey`, orders them by page, and returns rows with pagination. Approval/replay uses the same `rawStageKey`, so the data inspected and the data replayed have one scope.

## Flow invariants

1. A paginated API stream is fetched and staged completely before the mapping gate creates `WAITING_REVIEW`.
2. A packet raw-data request is scoped by `rawStageKey`, never by only the latest `sourceFileId` or latest Airflow runtime.
3. Every returned row identifies its `sourceUnitKey` and page for traceability.
4. Pagination is deterministic and bounded; the server never loads the entire stream into one response.
5. Runtime mapping validation reads the same staged stream scope as the raw-data viewer, while retaining bounded trace samples for the packet.
6. Approval replays every retained `STAGED` or `CONSUMED` page for the packet's `rawStageKey`.
7. Missing/expired staged payloads fail explicitly and do not silently fall back to an unrelated same-day file.

## Backend contract

Add a packet-scoped endpoint:

`GET /api/v1/review-packets/{packet_id}/raw-records?offset=0&limit=50`

Response fields:

- `packetId`, `rawStageKey`, `totalRecords`, `pageCount`
- `offset`, `limit`, `hasMore`
- `rows`: raw values plus `page`, `sourceUnitKey`, and row index

The endpoint reads the raw page payload from GridFS, converts each page to rows using the existing reader/signature machinery, and applies global offset/limit across the ordered stream. It must reject a packet without `rawStageKey` with a clear 409/404 response.

## Frontend behavior

Guided Review shows a `Raw stream data` panel in the mapping flow. It displays total records, page count, source unit/page provenance, and a paginated table. Loading the next table page calls the packet-scoped endpoint; it does not assume the packet's `samplePreview` is complete. Existing sample/AI mapping behavior remains bounded, but the operator can inspect every raw row before approving.

## Verification

- Backend tests prove stream scope excludes another stream on the same date, pagination spans page boundaries, and missing payloads are explicit.
- Mapping-flow tests prove raw viewer and runtime validation use the packet's `rawStageKey`.
- Frontend tests prove the table requests packet-scoped pages and renders navigation/counts.
- Existing approval/replay tests prove all staged pages still replay and are marked consumed.

