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

Dashboard operator có mật độ thông tin cao và phong cách chuyên nghiệp cho
payment reconciliation và schedule automation. Thiết kế ưu tiên tốc độ, độ
tương phản cao và tận dụng tối đa diện tích màn hình.

## Colors

- **Primary Accent (`#f0b90b`):** Signal gold cho action chính, active state indicator và operational control quan trọng.
- **Background Slate (`#0b0e11`, `#181d22`):** Nền slate tối, tạo tương phản cao và giảm mỏi mắt.
- **Status Indicators:** Green (`#0ecb81`) cho healthy/completed, Red (`#b44343`) cho failed/blocked, Amber (`#e6a23c`) cho waiting review.

## Typography

- **Primary Font:** Inter / Public Sans để dễ đọc trong table và metric.
- **Monospace Font:** JetBrains Mono / System Mono cho schedule crons, packet IDs và raw logs.

## Layout

- **Sidebar Width:** Navbar trái compact rộng 210px để tăng không gian ngang cho table.
- **Data Table:** Layout cột động, có width budget riêng cho Actions (tối thiểu 200px) và Runtime State để tránh cắt nội dung.

## Elevation & Depth

- Card trên dark surface phẳng với border 1px rõ ràng (`rgba(255,255,255,0.08)`).
- Glow nhẹ cho action control đang active/hover và status badge active.

## Shapes

- Corner radius compact (4px–8px), phù hợp mật độ dữ liệu kỹ thuật và hiệu suất cao.

## Components

- **Compact Action Toolbar:** Button icon + text có tooltip để thao tác nhanh, không làm rối chiều dọc hoặc ngang.
- **Slim Sidebar:** Navbar rộng 210px với icon badge và active indicator gọn.

## Do's and Don'ts

- **Do** bảo đảm mọi table action button hiển thị đầy đủ và gọn trên desktop tiêu chuẩn (1280px+).
- **Don't** dùng purple hoặc glassmorphism blur nặng làm giảm khả năng đọc text.
- **Do** dùng responsive tooltip hoặc cặp icon-text compact cho row có nhiều action.
