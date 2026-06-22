# Phase 2: Next.js Foundation — PLAN.md

## Objective

Dựng `frontend-next/` — base app Next.js chạy song song với FE cũ (Vite). Chưa migrate feature nào. Mục tiêu là có app Next.js chạy local được với shell cơ bản và hạ tầng FE mới.

**Không đụng:** backend, business logic, FE cũ (`frontend/`).

---

## Output

- `frontend-next/` là Next.js App Router app, chạy `npm run dev` được
- Layout root + sidebar shell + route placeholder cho các feature
- Global styles + design tokens
- API client wrapper trỏ vào backend hiện tại (`http://localhost:8000`)
- ESLint + Prettier + path alias (`@/` → `src/`)

---

## Tasks

### Wave 1: Project scaffolding

#### Task 1.1: Initialize Next.js project

- **Action:**
  - `cd frontend-next && npx create-next-app@latest . --typescript --app --tailwind --eslint --src-dir --no-import-alias`
  - Nếu interactive, dùng: `--ts --app --tailwind --eslint --src-dir`
  - Xoá `src/app/page.tsx` mặc định, giữ layout.tsx
- **Modified files:**
  - `frontend-next/package.json`
  - `frontend-next/tsconfig.json`
  - `frontend-next/next.config.ts`
  - `frontend-next/src/app/layout.tsx`
- **Acceptance criteria:**
  - `frontend-next/package.json` tồn tại, có scripts `dev`, `build`, `start`
  - `next dev` không crash
  - App router layout ở `src/app/layout.tsx`

#### Task 1.2: Setup path alias + code quality

- **Action:**
  - Thêm `@/*` path alias vào `tsconfig.json`:
    ```json
    "paths": { "@/*": ["./src/*"] }
    ```
  - Cài Prettier: `npm i -D prettier eslint-config-prettier`
  - Tạo `.prettierrc`:
    ```json
    { "semi": true, "singleQuote": true, "tabWidth": 2, "trailingComma": "es5" }
    ```
  - Merge ESLint config: thêm `prettier` vào `extends` cuối
- **Modified files:**
  - `frontend-next/tsconfig.json`
  - `frontend-next/.prettierrc` (new)
  - `frontend-next/eslint.config.mjs` (or `.js`)
- **Acceptance criteria:**
  - `tsconfig.json` có `paths["@/*"]`
  - `.prettierrc` tồn tại với config trên
  - `npx eslint src/` không lỗi (có thể có warning do template code)

#### Task 1.3: Setup proxy to backend

- **Action:**
  - Trong `next.config.ts`, thêm `rewrites`:
    ```ts
    async rewrites() {
      return [
        { source: '/api/:path*', destination: 'http://localhost:8000/api/:path*' }
      ];
    }
    ```
- **Modified files:**
  - `frontend-next/next.config.ts`
- **Acceptance criteria:**
  - `next.config.ts` có `rewrites` function
  - Request tới `/api/v1/...` từ browser được proxy tới `localhost:8000`

---

### Wave 2: Global styles + tokens

#### Task 2.1: Port design tokens + reset

- **Action:**
  - Copy token variables từ `frontend/styles/00-foundation.css` sang `frontend-next/src/app/globals.css`
  - Giữ lại Tailwind `@tailwind base/components/utilities` directives
  - Thêm CSS custom properties section sau Tailwind utilities
  - Chỉ lấy token variables (colors, spacing, font-size, border-radius), không lấy component classes
  - Bỏ `@tailwind base` nếu nó xung đột với foundation reset, giữ `@tailwind utilities`
- **Files to read first:**
  - `frontend/styles/00-foundation.css`
- **Modified files:**
  - `frontend-next/src/app/globals.css`
- **Acceptance criteria:**
  - `globals.css` chứa `--color-*`, `--spacing-*`, `--font-size-*` variables
  - Variables giống với `00-foundation.css`
  - `@tailwind utilities` vẫn còn

#### Task 2.2: Stylelint config

- **Action:**
  - Cài: `npm i -D stylelint stylelint-config-standard`
  - Tạo `.stylelintrc.json`:
    ```json
    { "extends": "stylelint-config-standard", "rules": { "at-rule-no-unknown": [true, { "ignoreAtRules": ["tailwind"] }] } }
    ```
- **Modified files:**
  - `frontend-next/.stylelintrc.json` (new)
- **Acceptance criteria:**
  - `.stylelintrc.json` tồn tại
  - `npx stylelint "src/**/*.css"` không crash

---

### Wave 3: App shell

#### Task 3.1: Root layout

- **Action:**
  - `src/app/layout.tsx`:
    - Import `globals.css`
    - Export metadata (title: "Adapter Dashboard")
    - Body wrap children trong `<AppShell>` (sẽ tạo ở task 3.2)
- **Files to read first:**
  - `frontend/app.js` (lines 80-200 for layout structure)
  - `frontend/styles/01-shell-components.css`
- **Modified files:**
  - `frontend-next/src/app/layout.tsx`
- **Acceptance criteria:**
  - Layout có `<html>` + `<body>` đúng chuẩn Next.js
  - Có `<AppShell>` wrapping children

#### Task 3.2: AppShell component

- **Action:**
  - Tạo `src/components/layout/app-shell.tsx`:
    ```tsx
    export default function AppShell({ children }: { children: React.ReactNode }) {
      return (
        <div className="app-shell">
          <AppSidebar />
          <main className="app-main">{children}</main>
        </div>
      );
    }
    ```
  - Tạo `src/components/layout/app-sidebar.tsx` với nav links:
    - Overview → `/`
    - Reconciliation → `/reconciliation`
    - Review Center → `/review-center`
    - Schedules → `/schedules`
    - Audit Log → `/audit-log`
    - Mapping Studio → `/mapping-studio`
  - CSS module cho sidebar: `src/components/layout/app-sidebar.module.css`
    - Fixed left, 240px width, dark background, nav items với hover/active states
  - Dùng `next/link` cho navigation
- **Files to read first:**
  - `frontend/styles/01-shell-components.css` (tham khảo sidebar styles hiện tại)
- **Modified files:**
  - `frontend-next/src/components/layout/app-shell.tsx` (new)
  - `frontend-next/src/components/layout/app-sidebar.tsx` (new)
  - `frontend-next/src/components/layout/app-sidebar.module.css` (new)
- **Acceptance criteria:**
  - Sidebar hiển thị 6 nav items
  - Click vào link chuyển route (dùng Link, không dùng a tag)
  - Sidebar có CSS module riêng

#### Task 3.3: Route placeholders

- **Action:**
  - Tạo các file sau (mỗi file là một page đơn giản với heading tên feature + `<PlaceholderShell>`):
    - `src/app/page.tsx` (Overview)
    - `src/app/reconciliation/page.tsx`
    - `src/app/review-center/page.tsx`
    - `src/app/schedules/page.tsx`
    - `src/app/audit-log/page.tsx`
    - `src/app/mapping-studio/page.tsx`
  - Placeholder content: `<h1>{Feature Name}</h1><p>Coming soon</p>` trong `<PageHeader>` wrapper
  - Tạo `src/components/ui/page-header.tsx` với title và optional description props
  - Tạo `src/components/layout/page-header.module.css`
- **Modified files:**
  - `frontend-next/src/app/page.tsx` (new)
  - `frontend-next/src/app/reconciliation/page.tsx` (new)
  - `frontend-next/src/app/review-center/page.tsx` (new)
  - `frontend-next/src/app/schedules/page.tsx` (new)
  - `frontend-next/src/app/audit-log/page.tsx` (new)
  - `frontend-next/src/app/mapping-studio/page.tsx` (new)
  - `frontend-next/src/components/ui/page-header.tsx` (new)
  - `frontend-next/src/components/layout/page-header.module.css` (new)
- **Acceptance criteria:**
  - 6 routes đều render được, không 404
  - Mỗi route có heading tương ứng

---

### Wave 4: API layer

#### Task 4.1: API client

- **Action:**
  - Tạo `src/lib/api/client.ts`:
    ```ts
    const BASE_URL = '/api/v1';

    export async function fetchJson<T>(path: string): Promise<T> {
      const res = await fetch(`${BASE_URL}${path}`, {
        headers: { Accept: 'application/json' },
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`API ${res.status}: ${text.slice(0, 200)}`);
      }
      return res.json();
    }

    export function apiUrl(path: string): string {
      return `${BASE_URL}${path}`;
    }
    ```
  - Tạo `src/types/api.ts`:
    ```ts
    export type ApiResponse<T> = { data: T; meta?: { total: number; limit: number; offset: number } };
    export type ApiError = { detail: string };
    ```
- **Files to read first:**
  - `frontend/src/core/api.js`
- **Modified files:**
  - `frontend-next/src/lib/api/client.ts` (new)
  - `frontend-next/src/types/api.ts` (new)
- **Acceptance criteria:**
  - `client.ts` export `fetchJson<T>()` generic function
  - `api.ts` có `ApiResponse<T>` type

---

## Verification

1. `cd frontend-next && npm run dev` — app chạy trên port 3000
2. Mở `http://localhost:3000` — thấy Overview page với sidebar
3. Click từng nav item — thấy route placeholder tương ứng
4. `npx tsc --noEmit` — 0 lỗi TypeScript
5. `npx eslint src/` — 0 lỗi
6. `npx prettier --check src/` — pass

## must_haves (goal-backward verification)

- [x] `frontend-next/` tồn tại và `npm run dev` chạy được
- [x] Layout root + sidebar shell + 6 route placeholders render được
- [x] Global CSS variables từ FE cũ được port
- [x] Path alias `@/` hoạt động
- [x] ESLint + Prettier config sẵn sàng
- [x] API client wrapper gọi được backend proxy
