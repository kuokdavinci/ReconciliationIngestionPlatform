# Next.js Migration Plan

## Mục tiêu

Migrate frontend hiện tại sang `Next.js` theo từng phase, giữ nguyên:

- backend API hiện tại
- business flow hiện tại
- pagination cho dataset lớn
- bulk selection / bulk write flow
- reconciliation / review / approval behavior

Mục tiêu chính không phải là rewrite UI cho đẹp hơn, mà là:

- giảm độ phình của `frontend/app.js`
- chuyển từ render string + inline style sang component architecture
- làm cho frontend dễ bảo trì, dễ mở rộng, dễ test hơn

---

## Nguyên tắc

1. Không đổi backend contract trong lúc migrate FE.
2. Không rewrite toàn bộ một lần.
3. Migrate theo feature, ưu tiên màn có ROI cao nhất.
4. Chỉ cắt FE cũ khi feature tương ứng trên Next.js đã đạt parity.
5. Pagination và bulk write là core behavior, không được đơn giản hóa đi.

---

## Kiến trúc đích

Frontend đích nên có dạng:

```text
frontend-next/
  app/
    layout.tsx
    page.tsx
    reconciliation/
      page.tsx
    review-center/
      page.tsx
    schedules/
      page.tsx
    audit-log/
      page.tsx
  components/
    ui/
    layout/
    reconciliation/
    review-center/
    schedules/
    audit/
  lib/
    api/
    format/
    date/
    state/
  styles/
  types/
```

Định hướng:

- `app/`: route shell
- `components/ui/`: component dùng chung
- `components/<feature>/`: component theo domain
- `lib/api/`: API client gọi backend hiện tại
- `lib/state/`: local feature state helpers
- `types/`: typed payloads map theo backend contract

### Kiến trúc thực thi đề xuất

Để tránh migrate nửa vời, nên chốt luôn một số quyết định kỹ thuật:

- `Next.js App Router`
- `TypeScript`
- `Client Components` cho dashboard screens có nhiều interaction
- `Server Components` chỉ dùng cho shell tĩnh hoặc static wrapper nếu cần
- `fetch` hoặc một `api client` mỏng, không đưa logic nghiệp vụ vào network layer
- `CSS Modules` hoặc `vanilla extracted CSS`

Khuyến nghị thực dụng nhất cho codebase này:

- dùng `CSS Modules` cho feature components
- giữ `global.css` cho tokens + reset + base layout
- không mang toàn bộ CSS cũ vào một file global mới

---

## Hiện trạng codebase cần map

### Frontend hiện tại

```text
frontend/
  app.js
  styles.css
  styles/
    00-foundation.css
    01-shell-components.css
    02-feature-review-reconciliation.css
    03-feature-guided-review.css
    04-overrides-responsive.css
  src/
    core/
    features/
      audit/
      automation/
      mapping-studio/
      reconciliation/
      review-center/
      review-runtime/
    shared/
      filters/
```

### Điểm nghẽn hiện tại

1. `frontend/app.js`
- vẫn là orchestration layer lớn
- route handling, event binding, polling, modal state, render trigger đang trộn cùng nhau

2. `render.js` theo feature
- đã tách ra nhưng vẫn đang render HTML string
- inline style còn nhiều
- khó tái sử dụng logic UI theo component tree

3. `styles.css` và inline styles
- đã tách file vật lý nhưng chưa hoàn tất componentization
- style ownership chưa gắn chặt với component ownership

4. State lifecycle
- state hiện là global mutable object
- local rerender thủ công
- modal state và selected row state đang bám sát implementation cũ

---

## Branch Strategy

### Branch nên dùng

- `main`
  - chỉ nhận thay đổi stable
- `feature/frontend-cleanup`
  - tiếp tục dọn FE hiện tại
- `feature/frontend-next-foundation`
  - dựng `frontend-next/`
- `feature/frontend-next-reconciliation`
  - migrate reconciliation
- `feature/frontend-next-review-center`
  - migrate review center

### Quy tắc

- mỗi phase lớn là một branch riêng
- không gom Phase 2, 3, 4 vào một PR khổng lồ
- mỗi PR phải có verification riêng

### Cỡ PR khuyến nghị

- foundation shell: nhỏ đến vừa
- reconciliation: vừa đến lớn
- review center: vừa đến lớn
- mapping studio: lớn, nên chia theo step nếu cần

---

## Folder Structure chi tiết cho `frontend-next`

```text
frontend-next/
  app/
    layout.tsx
    page.tsx
    reconciliation/
      page.tsx
      loading.tsx
      error.tsx
    review-center/
      page.tsx
    schedules/
      page.tsx
    audit-log/
      page.tsx
    mapping-studio/
      page.tsx
  components/
    ui/
      button/
      badge/
      panel/
      metric-card/
      dialog/
      data-table/
      empty-state/
      filter-bar/
      tabs/
      toast/
      skeleton/
    layout/
      app-shell/
      app-sidebar/
      topbar/
      page-header/
    reconciliation/
      run-status-panel/
      summary-strip/
      insight-grid/
      insight-card/
      insight-explain-modal/
      affected-preview/
      evidence-ledger/
      evidence-row/
      evidence-mobile-card/
      bulk-action-bar/
      pagination-bar/
    review-center/
      packet-list/
      packet-card/
      packet-detail/
      guided-review-modal/
      guided-scope-selector/
      recommendation-panel/
      decision-actions/
    schedules/
      schedule-overview/
      schedule-card/
    audit/
      audit-table/
      audit-filters/
    mapping-studio/
      source-selection/
      file-preview/
      mapping-editor/
      validation-panel/
      transformation-preview/
      version-history/
  lib/
    api/
      client.ts
      reconciliation.ts
      review-center.ts
      schedules.ts
      audit.ts
      mapping-studio.ts
    format/
      amount.ts
      number.ts
      date.ts
      text.ts
    state/
      reconciliation-store.ts
      review-center-store.ts
      schedules-store.ts
      audit-store.ts
      mapping-studio-store.ts
    adapters/
      reconciliation-adapter.ts
      review-center-adapter.ts
    constants/
    utils/
  hooks/
    use-toast.ts
    use-modal.ts
    use-deferred-render.ts
    use-paginated-table.ts
    use-bulk-selection.ts
  types/
    api.ts
    reconciliation.ts
    review-center.ts
    mapping.ts
  styles/
    globals.css
    tokens.css
```

---

## Mapping file cũ sang file mới

### Core utilities

| Cũ | Mới đề xuất |
|---|---|
| `frontend/src/core/api.js` | `frontend-next/lib/api/client.ts` + per-domain API files |
| `frontend/src/core/date.js` | `frontend-next/lib/format/date.ts` |
| `frontend/src/core/format.js` | `frontend-next/lib/format/*` |
| `frontend/src/core/status.js` | `frontend-next/lib/constants/status.ts` hoặc `lib/utils/status.ts` |
| `frontend/src/core/polling.js` | `frontend-next/hooks/*poll*` hoặc feature services |
| `frontend/src/core/state-helpers.js` | domain stores / domain reducers |

### Shared UI

| Cũ | Mới đề xuất |
|---|---|
| `frontend/src/shared/filters/render.js` | `components/ui/filter-bar/*` |
| `frontend/src/shared/filters/bind.js` | React controlled inputs + callbacks |

### Reconciliation

| Cũ | Mới đề xuất |
|---|---|
| `frontend/src/features/reconciliation/render.js` | nhiều component trong `components/reconciliation/*` |
| `frontend/src/features/reconciliation/bind.js` | event callbacks + custom hooks |
| `frontend/src/features/reconciliation/evidence.js` | `evidence-ledger` / `evidence-detail-dialog` |
| `frontend/src/features/reconciliation/insights.js` | `insight-grid`, `insight-card`, `insight-explain-modal` |

### Review Center

| Cũ | Mới đề xuất |
|---|---|
| `frontend/src/features/review-center/render.js` | `components/review-center/*` |
| `frontend/src/features/review-center/bind.js` | callbacks in page container |
| `frontend/src/features/review-center/guided-review.js` | modal flow components + hook |
| `frontend/src/features/review-center/selectors.js` | selectors in domain store |

### Mapping Studio

| Cũ | Mới đề xuất |
|---|---|
| `frontend/src/features/mapping-studio/render.js` | `components/mapping-studio/*` |
| `frontend/src/features/mapping-studio/bind.js` | form handlers + feature hook |

---

## API Strategy

## Mục tiêu

Giữ nguyên backend API nhưng thay cách FE gọi API cho rõ ràng hơn.

### Nguyên tắc

- Không gọi `fetch` trực tiếp rải rác trong component tree
- Tập trung API theo domain
- Chỉ parse response ở adapter layer
- Không nhét business inference vào UI

### Ví dụ

```text
lib/api/reconciliation.ts
  getRunStatus(partner, date)
  getStats(partner, date)
  getResults(partner, date, limit, offset)
  getInsights(partner, date, type)
  runReconciliation(payload)
  resolveReviewRecord(payload)
```

### Adapter layer cần làm gì

- normalize field names nếu backend cũ chưa ổn định
- convert `snake_case` / mixed response sang FE types ổn định
- giữ mapping logic ở một chỗ

### Adapter layer không nên làm gì

- không suy luận verdict từ raw text
- không đổi semantics của status
- không tự tạo business rule mới

---

## State Strategy

### Tại sao không nên giữ đúng kiểu state hiện tại

State hiện tại là một object global mutable, phù hợp cho app vanilla nhưng sẽ làm React app khó kiểm soát rerender và lifecycle.

### Đề xuất state theo domain

- mỗi feature có page container giữ state chính
- reusable hooks cho selection, pagination, modal
- tránh một store toàn cục khổng lồ trừ khi thực sự cần

### Reconciliation state target

```ts
type ReconciliationPageState = {
  partner: string;
  date: string;
  reconStatus: string;
  filters: {
    amountMin: string;
    amountMax: string;
    dateFrom: string;
    dateTo: string;
  };
  pagination: {
    limit: number;
    offset: number;
  };
  runStatus: ReconciliationRun | null;
  stats: ReconciliationStats | null;
  results: ReconciliationRow[];
  insights: {
    anomalies: InsightItem[] | null;
    patterns: InsightItem[] | null;
    recommendations: InsightItem[] | null;
  };
  selectedRows: Record<string, boolean>;
  selectedEvidenceRowId: string | null;
  explainItem: InsightItem | null;
  reviewedRecords: Record<string, boolean>;
};
```

### Hooks nên có

- `useReconciliationPageState`
- `useReconciliationFilters`
- `useReconciliationPagination`
- `useBulkSelection`
- `useInsightModal`
- `useEvidenceModal`
- `useDeferredInsights`

### Điều cần giữ nguyên

- filter local update không được làm chớp toàn page
- pagination state phải là source of truth cho API query
- bulk selection phải bám theo visible result set

---

## CSS Strategy

### Giai đoạn đầu

- dùng `globals.css` cho:
  - reset
  - tokens
  - app shell base
- dùng `*.module.css` cho từng component/feature

### Giai đoạn chuyển tiếp

- không bê nguyên toàn bộ CSS cũ vào 1 file
- có thể copy token và base classes cần thiết trước
- các component migrate xong thì dùng module riêng

### Mục tiêu cuối

- component nào sở hữu markup thì component đó sở hữu style chính
- giảm tối đa inline style
- chỉ giữ global class cho utility thật sự shared

---

## Testing Strategy

### 1. Visual parity checklist

Cho mỗi route, cần chụp lại:

- desktop
- mobile
- loading state
- empty state
- error state
- active modal state

### 2. Behavioral parity checklist

Với mỗi feature, cần test:

- initial load
- filter update
- pagination change
- row selection
- bulk actions
- modal open/close
- refresh flow
- polling flow

### 3. Regression focus đặc biệt

#### Reconciliation

- page size đổi đúng
- next/prev page đúng offset
- bulk selection chỉ áp dụng visible rows
- batch action gửi đúng selected keys
- explain modal không làm page nháy

#### Review Center

- packet selection đúng
- guided review step transitions đúng
- approve/reject side effects đúng

#### Mapping Studio

- preview đúng
- validation hiển thị đúng
- version restore đúng

### 4. Test layers khuyến nghị

- unit test cho adapter / formatter / selectors
- component test cho modal, tables, cards
- E2E test cho flows chính:
  - reconciliation pagination + bulk action
  - review packet approve flow
  - mapping validation flow

---

## Rollout Strategy chi tiết

### Cách 1: song song theo port

- FE cũ: `frontend/`
- FE mới: `frontend-next/`

Ưu điểm:

- an toàn
- dễ so sánh từng màn

Nhược điểm:

- có 2 app cần chạy

### Cách 2: reverse proxy theo route

- `/reconciliation` trỏ sang Next.js
- các route khác giữ app cũ

Ưu điểm:

- rollout thật sát production

Nhược điểm:

- setup phức tạp hơn

### Khuyến nghị

Ban đầu dùng song song theo port.

Khi `Reconciliation` ổn định mới tính đến route-based switch.

---

## Phase 4 chi tiết: Reconciliation

Đây là phase quan trọng nhất, nên breakdown sâu.

### 4.1 Mục tiêu cụ thể

Tái tạo toàn bộ màn `Reconciliation` trên Next.js với parity về:

- data loading
- interaction
- modal behavior
- pagination
- bulk write
- insight rendering

### 4.2 API dependencies

Màn này hiện đang phụ thuộc ít nhất vào:

- reconciliation run status
- reconciliation stats
- reconciliation results
- reconciliation insights
- reconciliation review record mutations

### 4.3 Component tree chi tiết

```text
ReconciliationPage
  ReconciliationToolbar
  RunStatusPanel
  SummaryStrip
  DeferredInsightSection
    InsightGrid
      InsightColumn
        InsightCard
  AffectedPreview
  EvidenceLedgerSection
    LedgerHeader
    ReconciliationStatusTabs
    ExplorerFilterBar
    EvidenceLedger
      DesktopLedgerTable
        EvidenceRow
      MobileLedgerCards
        MobileEvidenceCard
    PaginationBar
  BulkActionBar
  EvidenceDetailDialog
  InsightExplainDialog
  AdjustmentDialog
```

### 4.4 State ownership

| State | Owner |
|---|---|
| partner/date | page container or route/search params |
| filters | page container |
| pagination | page container |
| selected rows | bulk selection hook |
| selected evidence row | page container |
| explain item | page container |
| insights loading | insight hook |
| results loading | results hook |

### 4.5 Hooks breakdown

- `useReconciliationQueryParams`
- `useReconciliationData`
- `useReconciliationInsights`
- `useBulkSelection`
- `useEvidenceDialogs`
- `useResultsPagination`

### 4.6 Migration sequence nội bộ cho phase 4

1. Dựng page shell với mock data
2. Port toolbar + run status + summary strip
3. Port evidence ledger table
4. Port pagination
5. Port bulk selection + bulk action
6. Port insight cards
7. Port explain modal
8. Port evidence modal
9. Port adjustment modal
10. Nối API thật
11. So sánh parity với FE cũ

### 4.7 Tiêu chí done chi tiết

- route load đúng theo partner/date
- table render đúng page hiện tại
- changing page size refetch đúng
- next/prev page không lệch record window
- checkbox row hoạt động đúng
- select-all chỉ áp dụng visible mismatches
- bulk bar hiện/ẩn đúng
- Explain popup mở đúng item
- insight cards không chớp khi filter local
- mobile card view còn hoạt động

### 4.8 Rủi ro lớn nhất trong phase 4

1. State split sai chỗ, gây rerender quá nhiều
2. Pagination logic bị trộn giữa UI page index và backend offset
3. Bulk selection bị reset sai lúc refetch
4. Modal mount/unmount khác behavior cũ
5. Deferred insights làm user tưởng page bị treo

### 4.9 Cách giảm rủi ro

- giữ pagination contract bằng adapter rõ ràng
- viết component test cho `PaginationBar` và `BulkActionBar`
- dùng sample fixture từ API thật
- migrate từng cụm, không port toàn màn một phát

---

## Timeline đề xuất

Đây là timeline tương đối, không phải cam kết cứng.

### Tuần 1

- chốt plan
- dọn FE hiện tại thêm một ít
- dựng `frontend-next/`
- setup shell + tokens + primitives nền

### Tuần 2

- build static `Reconciliation` UI
- port table + cards + summary + pagination

### Tuần 3

- nối API thật cho `Reconciliation`
- port bulk action + modals + insights
- parity test

### Tuần 4

- migrate `Review Center` skeleton
- port packet list + detail + guided review modal

### Tuần 5+

- migrate `Schedules`, `Audit Log`
- sau đó mới đến `Mapping Studio`

---

## Decision Log nên ghi lại trong quá trình migrate

Trong quá trình làm, nên tạo thêm một file như:

`frontend-next/MIGRATION_DECISIONS.md`

Ghi các quyết định như:

- chọn CSS Modules hay không
- polling xử lý ở hook nào
- pagination state lấy từ search params hay local state
- rollout strategy nào được chọn

Điểm này quan trọng vì migration kéo dài nhiều phase, nếu không ghi lại thì rất dễ drift.

---

## Phase 0

### Mục tiêu

Khóa phạm vi migration và chuẩn bị nền.

### Việc cần làm

- Đóng băng thay đổi lớn về nghiệp vụ FE trong lúc migrate.
- Giữ nguyên route/backend contract hiện tại.
- Xác định rõ feature ưu tiên migrate trước.
- Hoàn tất dọn CSS base và giảm inline style ở các màn lớn.

### Output

- file plan này được chốt
- xác nhận scope là FE-only migration
- danh sách feature theo thứ tự migrate

### Done khi

- team thống nhất không đổi nghiệp vụ song song với migration
- đã có roadmap rõ và branch strategy rõ

---

## Phase 1

### Mục tiêu

Chuẩn hóa FE hiện tại trước khi đưa sang React/Next.

### Việc cần làm

- tiếp tục tách module trong FE hiện tại
- giảm inline style ở các feature lớn
- chuẩn hóa CSS tokens / component classes
- xác định reusable primitives hiện có

### Nên tách thành các primitive

- `Button`
- `Badge`
- `Panel`
- `MetricCard`
- `Modal`
- `FilterBar`
- `EmptyState`
- `Table`

### Output

- FE hiện tại bớt coupling hơn
- dễ map từ render string sang React components

### Done khi

- reconciliation markup đã tương đối class-based
- app shell / modal / filter / panel patterns đã rõ

---

## Phase 2

### Mục tiêu

Dựng base app Next.js song song, chưa thay FE cũ.

### Việc cần làm

- tạo app mới, ví dụ `frontend-next/`
- setup `Next.js` với `TypeScript`
- setup lint / format / path alias
- setup global styles và design tokens
- setup API client wrapper trỏ vào backend hiện tại

### Khuyến nghị

- dùng `App Router`
- dùng client components cho dashboard interactions
- SSR không phải ưu tiên chính ở giai đoạn đầu

### Output

- app Next.js chạy độc lập
- có shell trống và hạ tầng FE mới

### Done khi

- `frontend-next` có thể chạy local
- có layout root, sidebar shell cơ bản, route placeholder

---

## Phase 3

### Mục tiêu

Migrate design system và app shell trước.

### Việc cần làm

- dựng sidebar
- dựng topbar
- dựng page container
- dựng modal root
- dựng toast / notification
- dựng primitives dùng chung

### Component target

- `AppSidebar`
- `Topbar`
- `AppShell`
- `PageSection`
- `Button`
- `Badge`
- `Panel`
- `MetricCard`
- `Dialog`

### Output

- giao diện shell đồng nhất
- feature sau đó chỉ cần gắn vào shell

### Done khi

- nhìn app mới đã giống structure app cũ
- có thể render static mock cho các route chính

---

## Phase 4

### Mục tiêu

Migrate `Reconciliation` trước.

### Lý do ưu tiên

- đây là màn đang phình to nhất
- đang chứa nhiều state, modal, filter, insight, table, pagination
- migrate màn này xong sẽ giảm phần lớn complexity frontend

### Component breakdown đề xuất

- `ReconciliationPage`
- `RunStatusPanel`
- `SummaryStrip`
- `InsightGrid`
- `InsightCard`
- `InsightExplainModal`
- `AffectedPreview`
- `EvidenceLedger`
- `EvidenceRow`
- `MobileEvidenceCard`
- `BulkActionBar`
- `PaginationBar`

### State cần giữ nguyên behavior

- filter state
- pagination state
- selected rows
- selected evidence row
- explain modal item
- deferred insight loading

### Bất biến phải giữ

- `limit/offset` logic
- DB pagination behavior
- bulk selection theo visible rows
- bulk review / bulk write flow
- local rerender behavior tương đương để không chớp UI

### Output

- tab reconciliation chạy hoàn chỉnh trên Next.js

### Done khi

- parity với FE cũ về:
  - run status
  - summary
  - insights
  - evidence table
  - mobile card view
  - filters
  - pagination
  - bulk actions
  - explain / evidence popup

---

## Phase 5

### Mục tiêu

Migrate `Review Center`.

### Component breakdown đề xuất

- `ReviewCenterPage`
- `ReviewPacketList`
- `ReviewPacketCard`
- `ReviewPacketDetail`
- `GuidedReviewModal`
- `GuidedScopeSelector`
- `RecommendationPanel`
- `ReviewDecisionActions`

### Rủi ro chính

- nhiều popup / modal state
- nhiều step transition
- mapping proposal + review packet coupling

### Output

- review center và guided review flow chạy được trên Next.js

### Done khi

- approve / reject / open review behavior khớp FE cũ

---

## Phase 6

### Mục tiêu

Migrate `Schedules` và `Audit Log`.

### Việc cần làm

- chuyển automation hiện tại thành route `Schedules`
- migrate polling UI
- migrate audit log table + filters

### Output

- toàn bộ 4 route chính đã có bản Next.js:
  - review-center
  - reconciliation
  - schedules
  - audit-log

### Done khi

- main navigation không còn phụ thuộc FE cũ

---

## Phase 7

### Mục tiêu

Migrate `Mapping Studio` sau cùng.

### Lý do để sau

- đây là phần form-heavy nhất
- có nhiều preview / validation / config editing state
- nên tận dụng primitives và modal system đã ổn định từ các phase trước

### Component breakdown đề xuất

- `MappingStudioPage`
- `SourceSelectionStep`
- `FilePreviewPanel`
- `MappingEditorTable`
- `ValidationResultPanel`
- `TransformationPreview`
- `VersionHistoryPanel`

### Output

- mapping studio được React hóa sau khi core dashboard đã ổn định

### Done khi

- upload / preview / validation / review handoff parity với FE cũ

---

## Phase 8

### Mục tiêu

Switch dần từ FE cũ sang Next.js.

### Cách làm

- chạy FE mới song song
- mở theo feature flag hoặc theo route
- cho phép rollout từng màn

### Ví dụ rollout

1. mở `reconciliation` trên Next.js
2. giữ `review-center` trên FE cũ
3. sau khi ổn, chuyển `review-center`
4. sau cùng mới cắt toàn bộ FE cũ

### Output

- giảm rủi ro rollout
- rollback dễ nếu có regression

### Done khi

- traffic chính đã chạy trên Next.js ổn định

---

## Phase 9

### Mục tiêu

Dọn hậu migration.

### Việc cần làm

- xóa code render string cũ
- xóa `frontend/app.js` orchestration cũ khi không còn dùng
- gộp docs frontend mới
- chuẩn hóa build/deploy frontend
- thêm test coverage cho các flow quan trọng

### Output

- chỉ còn một frontend source of truth

### Done khi

- FE cũ không còn route active
- không còn duplicate implementation

---

## Thứ tự ưu tiên migrate

1. `Reconciliation`
2. `Review Center`
3. `Schedules`
4. `Audit Log`
5. `Mapping Studio`

Lý do:

- `Reconciliation` đang đau nhất và phình nhất
- `Review Center` là màn quan trọng thứ hai
- `Schedules` và `Audit Log` tương đối thẳng hơn
- `Mapping Studio` nên để sau cùng vì complexity form/state cao

---

## Những gì không nên làm

- không rewrite toàn bộ một branch lớn rồi mới test
- không đổi backend contract giữa lúc migrate
- không bỏ pagination để “đơn giản hóa UI”
- không bỏ bulk flow để “dễ component hóa”
- không migrate `Mapping Studio` đầu tiên

---

## Rủi ro chính

### 1. UI parity drift

Component mới có thể khác behavior cũ nếu chỉ nhìn UI mà không bám state flow.

### 2. Modal / popup state drift

Hiện tại modal state nằm khá gần feature logic. Khi tách component cần giữ lifecycle cẩn thận.

### 3. Pagination / bulk flow regression

Đây là khu vực có giá trị vận hành thật, không được làm nhẹ tay.

### 4. Mixed frontend period

Trong thời gian chạy song song 2 frontend, docs và dev workflow có thể rối nếu không ghi rõ source of truth.

---

## Tiêu chí thành công

Migration được xem là thành công khi:

- frontend mới dễ đọc hơn frontend cũ
- mỗi route chính có component tree rõ ràng
- `app.js` kiểu cũ không còn là điểm nghẽn
- pagination / large dataset / bulk write vẫn hoạt động như hiện tại
- UI changes không làm lệch nghiệp vụ vận hành

---

## Khuyến nghị thực thi ngay

Thứ tự pragmatic nhất từ bây giờ:

1. dọn tiếp `reconciliation` hiện tại cho sạch hơn
2. tạo `frontend-next/`
3. dựng shell + primitives
4. migrate `reconciliation` đầu tiên

Đây là đường đi ít rủi ro nhất và cho ROI cao nhất.
