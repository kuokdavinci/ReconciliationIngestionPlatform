---
name: Adapter Reconciliation & Automation Platform
colors:
  primary: "#f0b90b"
  primary-hover: "#f6cf3c"
  bg-dark: "#0b0e11"
  bg-surface: "#181d22"
  bg-surface-hover: "#222830"
  border: "rgba(255, 255, 255, 0.08)"
  border-highlight: "rgba(240, 185, 11, 0.25)"
  text-primary: "#f8f5ef"
  text-muted: "rgba(236, 234, 227, 0.64)"
  status-matched: "#0ecb81"
  status-unmatched: "#b44343"
  status-warning: "#e6a23c"
typography:
  h1: { fontFamily: Inter, fontSize: 24px, fontWeight: 700, lineHeight: 1.2 }
  h2: { fontFamily: Inter, fontSize: 18px, fontWeight: 600, lineHeight: 1.3 }
  body-md: { fontFamily: Inter, fontSize: 14px, fontWeight: 400, lineHeight: 1.5 }
  body-sm: { fontFamily: Inter, fontSize: 12.5px, fontWeight: 400, lineHeight: 1.4 }
  mono: { fontFamily: "JetBrains Mono", fontSize: 12px, fontWeight: 400, lineHeight: 1.4 }
rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
components:
  sidebar:
    width: "210px"
    backgroundColor: "{colors.bg-dark}"
    borderColor: "{colors.border}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#12161a"
    rounded: "{rounded.sm}"
  button-action:
    padding: "6px 10px"
    fontSize: "12px"
    rounded: "{rounded.sm}"
---

# Adapter Reconciliation & Automation Platform Design System

## Overview
A high-density, professional operator dashboard for payment reconciliation and schedule automation. Designed for speed, high contrast, and maximum screen real-estate utilization.

## Colors
- **Primary Accent (`#f0b90b`):** Signal gold for primary actions, active state indicators, and key operational controls.
- **Background Slate (`#0b0e11`, `#181d22`):** Deep dark slate background providing maximum contrast and reducing visual fatigue.
- **Status Indicators:** Green (`#0ecb81`) for healthy/completed, Red (`#b44343`) for failed/blocked, Amber (`#e6a23c`) for waiting review.

## Typography
- **Primary Font:** Inter / Public Sans for clean legibility in tables and metrics.
- **Monospace Font:** JetBrains Mono / System Mono for schedule crons, packet IDs, and raw logs.

## Layout
- **Sidebar Width:** Compact 210px left navbar to maximize horizontal table space.
- **Data Table:** Dynamic column layout with dedicated width budgets for Actions (minimum 200px) and Runtime State to prevent content truncation.

## Elevation & Depth
- Flat dark surface cards with crisp 1px borders (`rgba(255,255,255,0.08)`).
- Subtle glow effects on active/hovered action controls and active status badges.

## Shapes
- Compact corner radius (4px - 8px) for technical, high-efficiency data density.

## Components
- **Compact Action Toolbar:** Icon + text buttons with tooltips for fast execution without vertical or horizontal clutter.
- **Slim Sidebar:** 210px width navbar with icon badges and sleek active indicators.

## Do's and Don'ts
- **Do** ensure all table action buttons remain fully visible and uncluttered on standard desktop screen sizes (1280px+).
- **Don't** use purple or heavy blur glassmorphism that obscures text readability.
- **Do** use responsive tooltips or compact icon-text pairs for multi-action rows.
