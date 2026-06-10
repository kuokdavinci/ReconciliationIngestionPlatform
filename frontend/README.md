# Frontend Dashboard

Vite-served Vanilla JS SPA for the operations and reconciliation dashboard.

## Run

Start backend first:

```bash
uv run python run.py --serve --port 8000
```

Then run the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Runtime Contract

- dev server: Vite
- default port: `5173`
- API proxy: `/api` -> `http://localhost:8000`

This proxy is configured in `frontend/vite.config.js`.

## Current Views

Routes reflected in `frontend/app.js`:

| Route | View |
|-------|------|
| `#review-center` | Review Center |
| `#reconciliation` | Reconciliation |
| `#mapping-studio` | Mapping Studio |
| `#automation` | Automation |

`#review-queue` is still normalized to `#review-center` for backward compatibility with older links.

## Current UX Notes

- `Review Center` is the default operational entry and loads the `pending` tab first.
- `Decision History` is loaded lazily when the user opens that tab.
- `Guided Review` is a single review panel with summary, AI draft mapping status, and decision actions.
- `Mapping Studio` remains the place to create or adjust draft mappings before approval.

## API Groups Used

The frontend currently consumes these backend groups:

- `/api/v1/insights/*`
- `/api/v1/reconciliation/*`
- `/api/v1/data/*`
- `/api/v1/mappings`
- `/api/v1/mapping/*`
- `/api/v1/operations/intake`
- `/api/v1/review-packets/*`
- `/api/v1/automation/*`
- `/api/v1/copilot/*`

## Main Files

- `index.html`: app shell
- `app.js`: route handling, rendering, fetch calls, action wiring
- `styles.css`: dashboard styling
- `vite.config.js`: dev/build config and backend proxy
- `server.py`: legacy helper, not the primary development path
