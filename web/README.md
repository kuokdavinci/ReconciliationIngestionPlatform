# Adapter Service Operations Dashboard

Static mock-first dashboard for the Adapter Service repository.

## Run

Mock-only mode can be opened directly in a browser:

```powershell
.\web\index.html
```

Live API mode is best run through the included proxy server:

```powershell
uv run python run.py serve --port 8000
python web\server.py --port 5173 --api http://localhost:8000
```

Then open `http://localhost:5173` and switch `Data Source` to `Live API`.

## Files

- `index.html` - app shell
- `styles.css` - responsive admin UI styling
- `mock-data.js` - mock records shaped after repository services and collections
- `app.js` - vanilla JS routing, rendering, filters, and mock actions
- `server.py` - optional local static server with `/api` proxy to FastAPI

## Integration Notes

All dashboard tabs connect to live API endpoints:

- `/api/v1/insights/summary` — Overview metrics + AI insights
- `/api/v1/insights/discrepancies` — Discrepancy analysis
- `/api/v1/reports/daily` — Daily reconciliation report
- `/api/v1/reconciliation/results` — Reconciliation results browser
- `/api/v1/reconciliation/stats` — Reconciliation health widget data
- `/api/v1/mappings` — Mapping Configs tab (active configs per partner)
- `/api/v1/data/transactions` — Data Explorer transaction browser
- `/api/v1/data/files` — File listing
- `/api/v1/data/stats` — Data volume stats
