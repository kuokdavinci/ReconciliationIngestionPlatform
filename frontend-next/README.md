# Adapter Dashboard (Next.js)

Frontend active của Reconciliation Ingestion Platform — xây dựng bằng Next.js
16 App Router, React 19, TypeScript 5 và Tailwind CSS v4.

## Các page

| Route | Mô tả |
|-------|-------------|
| `/` | Overview / dashboard home |
| `/reconciliation` | Reconciliation results, stats, and insights |
| `/review-center` | Guided review + approval workflows for mapping changes |
| `/mapping-studio` | Draft mapping configuration wizard |
| `/schedules` | Partner fetch schedule management |
| `/audit-log` | Audit event history |

## Quick Start

```bash
# Cài dependency
npm install

# Chạy dev server (proxy API tới localhost:8000)
npm run dev

# Build production
npm run build
```

Script `build` của repository đã dùng Webpack path đã được xác minh
(`next build --webpack`).

Dev server chạy tại `http://localhost:3000` và proxy request `/api/*` tới
`http://localhost:8000` (cấu hình trong `next.config.ts`).

## Tech Stack

- **Framework:** Next.js 16 (App Router)
- **Language:** TypeScript 5
- **Styling:** Tailwind CSS v4
- **Linting:** ESLint 9 + Prettier 3

## Code Quality

```bash
npm run lint        # ESLint
npm run typecheck   # Type check
npx prettier --check src/  # Kiểm tra format
npm run build # Production build dùng trong CI
npm run playwright:install # Cài browser test local
npm run test:e2e     # Playwright interaction smoke tests
```

Browser smoke tests khởi động production Next.js server và mock request
`/api/**`, nên không cần backend service. Từ checkout mới, chạy `npm run build`
trước `npm run test:e2e` local.

## Cấu trúc project

```
src/
├── app/           # App Router pages (6 routes)
├── components/    # React components (ui/, layout/, feature-specific/)
├── lib/           # API client + state stores + helpers
└── types/         # TypeScript interfaces
```
