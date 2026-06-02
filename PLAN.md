# UI/UX Redesign Implementation Plan: Stitch AI Fintech Reconciliation Dashboard (Dark Mode Only)

This document details the plan to redesign the Adapter Service UI/UX into the premium, state-of-the-art **AdapterService** interface. The redesign will follow a high-contrast dark theme (Matte Black and Golden Yellow accents) to achieve an authoritative, institutional-grade, and energetic visual style (Mission Control / Tech-Brutalist).

---

## 🎨 Design Vision & Theme (High-Contrast Dark Mode)

*   **Aesthetic:** Modern Minimalism with a Tech-Brutalist edge.
*   **Colors:** Deep Matte Black/Blue canvas (`#0b1326` to `#060e20`), Gold/Yellow accents (`#fbbf24`), Luminous Blues/Greys (`#dae2fd`), and highly saturated semantic indicators (Success Green `#10b981`, Error Red `#ef4444`).
*   **Key Design Elements:** No soft shadows; instead, uses sharp 1px solid borders and tonal layering to convey hierarchy and depth. Focuses on premium, clean typography and responsive layouts.

---

## 🛠️ Implementation Phases

### Phase 1: Design Tokens & Base Styles
**Files to modify:** `web/styles.css`, `web/index.html`
*   Define design tokens via CSS variables for the dark theme.
*   Import **Inter** font family and **Material Symbols Outlined** icons.
*   Establish layout container grids and base UI elements (buttons, tables, inputs).

### Phase 2: Premium Navigation Shell & Header
**Files to modify:** `web/index.html`, `web/app.js`
*   Rebuild the layout shell with a persistent left sidebar containing:
    *   Dynamic brand mark (AS -> AdapterService) with golden accents.
    *   Active indicators for navigation links with golden left-borders.
*   Top bar with global partner selection dropdown, date filter, and system status indicator.

### Phase 3: Dashboard Overview & AI Insights
**Files to modify:** `web/app.js`, `web/styles.css`
*   **KPI Cards Grid:** High-contrast cards for metrics, with real circular SVG progress rings.
*   **Reconciliation Status Breakdown:** Progress bars showing matched ratios, missing internal, and missing partner records.
*   **AI Insights Panel:** A feed displaying generative insights cards (e.g., anomalies in Momo API streams) categorized by focus.

### Phase 4: Reconciliation Results List & Ledger
**Files to modify:** `web/app.js`
*   **High-Density Ledger:** Table format using `font-variant-numeric: tabular-nums` for precise alignment of financial values.
*   **Status Badges:** Low-contrast pill-shaped badges (10% background opacity + 100% text color opacity) matching semantic statuses.
*   **Interactive Row Actions:** Add checkbox multi-selects and instant status filtering.

### Phase 5: Data Mapping Configuration UI
**Files to modify:** `web/app.js`
*   Visual fields mapping layout matching the `data_mapping_configuration` layout.

### Phase 6: Scheduler & Logs Console
**Files to modify:** `web/app.js`
*   Consolidated scheduler panel containing partner jobs, status indicators, and live log command output container.

### Phase 7: Polish & Transitions
**Files to modify:** `web/styles.css`, `web/app.js`
*   Add micro-animations (subtle hover scale, active button depression).
*   Add clean loading skeletons and error handlers.
