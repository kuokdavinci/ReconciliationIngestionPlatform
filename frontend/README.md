# Adapter Service Operations Dashboard

Vanilla JS Single-Page Application for the Reconciliation Ingestion Platform.

## Routes

| Route | View | Description |
|-------|------|-------------|
| `#command-center` | Command Center | Top-level metrics, AI risk insight tabs (Operational / Partner Trends / Data Inconsistencies), action queue |
| `#data-intake` | Data Intake | Partner-level summary cards (ACTIVE/NEEDS_REVIEW/BLOCKED/NO_ACTIVITY), activity feed, pending review items |
| `#review-center` | Review Center | Approval desk with right-side packet drawer, validation gates, approve/reject/send-to-studio actions |
| `#reconciliation` | Reconciliation | Deterministic mismatch review with status filter and pagination |
| `#mapping-studio` | Mapping Studio | 3-step proposal workflow (upload → preview/tweak → validate/handoff) |
| `#automation` | Automation | Scheduler job visibility, pending packets per partner, Run Now execution |

## Run

```bash
# Terminal 1 — Start the FastAPI backend
uv run python run.py serve --port 8000

# Terminal 2 — Start the Vite frontend dev server
cd frontend
npm run dev
```

Then open `http://localhost:5173`.

## Files

- `index.html` — App shell with nav, header, viewport
- `styles.css` — Responsive admin UI (dark sidebar, panels, review drawer, gate indicators)
- `app.js` — Vanilla JS SPA (~4800 lines): routing, rendering, filters, fetch, action bindings
- `vite.config.js` — Vite configuration containing the `/api` reverse proxy to FastAPI backend
- `server.py` — Legacy static file server (for reference)

## API Endpoints Used

| Endpoint | View | Purpose |
|----------|------|---------|
| `GET /api/v1/insights/summary` | Command Center | AI insights summary + metrics |
| `GET /api/v1/insights/discrepancies` | Command Center | Focus-specific anomaly analysis |
| `GET /api/v1/reconciliation/results` | Reconciliation | Paginated reconciliation results |
| `GET /api/v1/reconciliation/stats` | Command Center | Aggregated reconciliation stats |
| `GET /api/v1/mappings` | Review Center, Studio | List mapping configs by partner |
| `GET /api/v1/data/transactions` | (data explorer) | Browse canonical transactions |
| `GET /api/v1/data/files` | (data explorer) | File listing |
| `GET /api/v1/data/stats` | All views | Data volume statistics |
| `GET /api/v1/operations/intake` | Data Intake | Partner state + activity feed |
| `GET /api/v1/review-packets` | Review Center | List pending/historic packets |
| `GET /api/v1/review-packets/{id}` | Review Center | Packet detail |
| `POST /api/v1/review-packets/{id}/approve-activate` | Review Center | Approve + activate |
| `POST /api/v1/review-packets/{id}/approve-keep-current` | Review Center | Approve keep current |
| `POST /api/v1/review-packets/{id}/reject` | Review Center | Reject |
| `POST /api/v1/review-packets/{id}/send-to-studio` | Review Center → Studio | Handoff to studio |
| `GET /api/v1/automation/jobs` | Automation | Job visibility with packet counts |
| `POST /api/v1/automation/jobs/{partner}/run` | Automation | Run Now real execution |
| `POST /api/v1/mapping/ai-generate` | Studio / Review Center | AI field mapping from sample |
| `GET /api/v1/copilot/context?partner=X&date=Y&screen=Z` | All views | Contextual Copilot recommendation per screen |
| `GET /api/v1/copilot/context/file/{file_id}` | All views | Copilot context for specific file |
| `POST /api/v1/copilot/actions/{action_key}` | All views | Execute Copilot action |
| `POST /api/v1/review-packets/{id}/generate-ai-mapping` | Review Center | AI-generate mapping from packet samples |
| `POST /api/v1/review-packets/{id}/save-draft-mapping` | Review Center | Save inline draft mapping edits |
| `GET /api/v1/reconciliation/insights` | Reconciliation | AI-powered reconciliation insights (summary/anomalies/patterns/recommendations) |
