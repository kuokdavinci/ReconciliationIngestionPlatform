---
name: Precision Fintech
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#45464d'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#76777d'
  outline-variant: '#c6c6cd'
  surface-tint: '#565e74'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#131b2e'
  on-primary-container: '#7c839b'
  inverse-primary: '#bec6e0'
  secondary: '#0051d5'
  on-secondary: '#ffffff'
  secondary-container: '#316bf3'
  on-secondary-container: '#fefcff'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#002113'
  on-tertiary-container: '#009668'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dae2fd'
  primary-fixed-dim: '#bec6e0'
  on-primary-fixed: '#131b2e'
  on-primary-fixed-variant: '#3f465c'
  secondary-fixed: '#dbe1ff'
  secondary-fixed-dim: '#b4c5ff'
  on-secondary-fixed: '#00174b'
  on-secondary-fixed-variant: '#003ea8'
  tertiary-fixed: '#6ffbbe'
  tertiary-fixed-dim: '#4edea3'
  on-tertiary-fixed: '#002113'
  on-tertiary-fixed-variant: '#005236'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  data-mono:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  container-max: 1440px
  gutter: 24px
---

## Brand & Style
The design system is engineered for high-stakes financial environments where clarity, speed of cognition, and trust are paramount. The aesthetic is **Modern Minimalist**, leaning into a corporate-professional ethos that prioritizes data density without sacrificing legibility. 

The visual language communicates authority through a high-contrast palette and a structured, "data-first" hierarchy. By utilizing a card-based architecture and ample negative space, the system reduces cognitive load, allowing users to navigate complex financial landscapes—such as reconciliation, asset management, and risk analysis—with absolute confidence. The emotional response is one of calm control and technical precision.

## Colors
The color strategy employs a core of **Deep Navy** for structural elements and primary navigation to establish a foundation of stability. **Professional Blue** is utilized for primary actions and interactive states, ensuring high discoverability.

The functional palette is strictly semantic:
- **Success Green (#10B981):** Reserved for matched records, positive balances, and completed transactions.
- **Warning Orange (#F59E0B):** Indicates pending states, soft limits, or items requiring attention.
- **Alert Red (#EF4444):** Dedicated to mismatches, critical errors, or negative financial trends.

Backgrounds utilize a cool neutral slate (#F8FAFC) to differentiate card surfaces from the canvas, while text colors vary from Deep Navy for headings to a muted slate for secondary metadata.

## Typography
This design system utilizes **Inter** exclusively to leverage its exceptional legibility at small sizes and its neutral, systematic character. 

Key typographic principles:
- **Numerical Precision:** For financial data and tables, use the `data-mono` variant which enables tabular figures (`tnum`) to ensure columns of numbers align perfectly.
- **Hierarchy:** Bold weights are reserved for structural headings and primary KPIs. 
- **Scale:** On mobile devices, `headline-lg` should scale down to 24px to maintain readability within tighter viewports.
- **Contrast:** Secondary information uses a reduced font size and a lighter gray weight to ensure the primary data remains the focal point.

## Layout & Spacing
The layout follows a **12-column fluid grid** for desktop, transitioning to a single-column stack for mobile. A strict 8px spacing scale governs all dimensions, ensuring a rhythmic and predictable UI.

- **Desktop:** 12 columns, 24px gutters, 32px side margins.
- **Tablet:** 8 columns, 16px gutters, 24px side margins.
- **Mobile:** 4 columns, 16px gutters, 16px side margins.

Content is organized into "Financial Cards" that act as the primary containers. Large dashboards should utilize a "Sticky Sidebar" for global navigation and a "Fixed Header" for context-switching and search. Data-heavy tables should allow for horizontal scrolling on smaller breakpoints while keeping the primary identifier column (e.g., Transaction ID) frozen.

## Elevation & Depth
Depth is used sparingly to maintain a clean, professional profile. This design system utilizes a **Tonal Layering** approach combined with **Ambient Shadows**:

- **Level 0 (Background):** The base canvas uses the Neutral color (#F8FAFC).
- **Level 1 (Default Surface):** Cards and main content areas use a pure white background with a subtle 1px border (#E2E8F0).
- **Level 2 (Hover/Active):** Interactive cards utilize a soft, diffused shadow (0px 4px 12px rgba(15, 23, 42, 0.05)) to indicate interactivity.
- **Level 3 (Overlay):** Modals and dropdowns use a more pronounced shadow (0px 12px 32px rgba(15, 23, 42, 0.1)) and a slight background dimming to focus the user's attention.

Avoid heavy blurs or vibrant glows to keep the interface grounded and serious.

## Shapes
The shape language is **Soft (Radius: 4px - 8px)**. This choice strikes a balance between the clinical coldness of sharp corners and the playfulness of pill shapes.

- **Buttons & Inputs:** 4px radius (Soft) for a precise, engineered look.
- **Cards & Modals:** 8px radius (rounded-lg) to provide a gentle container for dense data.
- **Status Badges:** 4px radius to match buttons, maintaining consistency across interactive elements.

Data visualization elements (like bar charts) should use flat tops (0px radius) to ensure mathematical accuracy is visually represented.

## Components
Consistent component styling is the backbone of this design system:

- **Buttons:** 
  - **Primary:** Solid Deep Navy or Professional Blue with white text.
  - **Secondary:** Outline Professional Blue with a 1px stroke.
- **Data Tables:** Use a clean, borderless style with a 1px horizontal divider (#F1F5F9). Implement zebra-striping on hover rather than fixed alternating colors to reduce visual noise. Headers must be `label-md` with subtle sorting icons.
- **Status Chips:** Small, low-contrast badges. Use a background opacity of 10% of the semantic color (e.g., 10% Success Green) with 100% opacity text for the label.
- **Input Fields:** Use a 1px border (#CBD5E1) that shifts to Professional Blue on focus. Include clear error states using Alert Red for both the border and supporting helper text.
- **KPI Cards:** Features a bold `headline-md` for the value, a `label-md` for the title, and a small trend indicator (Success Green or Alert Red) in the bottom corner.
- **Checkboxes & Radios:** Use the Professional Blue for selected states to ensure high visibility against the neutral background.