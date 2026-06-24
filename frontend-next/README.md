# Adapter Dashboard (Next.js)

Active frontend for the Reconciliation Ingestion Platform — built with Next.js 16 App Router, React 19, TypeScript 5, and Tailwind CSS v4.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Overview / dashboard home |
| `/reconciliation` | Reconciliation results, stats, and insights |
| `/review-center` | Guided review + approval workflows for mapping changes |
| `/mapping-studio` | Draft mapping configuration wizard |
| `/schedules` | Partner fetch schedule management |
| `/audit-log` | Audit event history |

## Quick Start

```bash
# Install dependencies
npm install

# Start dev server (proxies API to localhost:8000)
npm run dev

# Build for production
npm run build
```

The dev server runs on `http://localhost:3000` and proxies `/api/*` requests to `http://localhost:8000` (configured in `next.config.ts`).

## Tech Stack

- **Framework:** Next.js 16 (App Router)
- **Language:** TypeScript 5
- **Styling:** Tailwind CSS v4
- **Linting:** ESLint 9 + Prettier 3

## Code Quality

```bash
npm run lint        # ESLint
npx tsc --noEmit    # Type check
npx prettier --check src/  # Format check
```

## Project Structure

```
src/
├── app/           # App Router pages (6 routes)
├── components/    # React components (ui/, layout/, feature-specific/)
├── lib/           # API client + state stores + helpers
└── types/         # TypeScript interfaces
```

## Legacy

The old `frontend/` (Vite + vanilla JS) dashboard in the repo root is kept as a legacy/reference implementation. All active development is in this directory.
