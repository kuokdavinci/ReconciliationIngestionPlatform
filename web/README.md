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

Live API currently uses the existing insights endpoints:

- `/api/v1/insights/summary`
- `/api/v1/insights/discrepancies`
- `/api/v1/reports/daily`

Other operational modules still use mock data until matching backend endpoints are added.
