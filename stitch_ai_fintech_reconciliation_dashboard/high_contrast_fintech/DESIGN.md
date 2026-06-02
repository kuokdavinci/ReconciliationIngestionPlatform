---
name: High-Contrast Fintech
colors:
  surface: '#0b1326'
  surface-dim: '#0b1326'
  surface-bright: '#31394d'
  surface-container-lowest: '#060e20'
  surface-container-low: '#131b2e'
  surface-container: '#171f33'
  surface-container-high: '#222a3d'
  surface-container-highest: '#2d3449'
  on-surface: '#dae2fd'
  on-surface-variant: '#d3c5ac'
  inverse-surface: '#dae2fd'
  inverse-on-surface: '#283044'
  outline: '#9c8f79'
  outline-variant: '#4f4633'
  surface-tint: '#f9bd22'
  primary: '#ffe1a7'
  on-primary: '#402d00'
  primary-container: '#fbbf24'
  on-primary-container: '#6c4f00'
  inverse-primary: '#795900'
  secondary: '#7bd0ff'
  on-secondary: '#00354a'
  secondary-container: '#00a6e0'
  on-secondary-container: '#00374d'
  tertiary: '#ffdcdd'
  on-tertiary: '#67001b'
  tertiary-container: '#ffb5b9'
  on-tertiary-container: '#aa0032'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdf9f'
  primary-fixed-dim: '#f9bd22'
  on-primary-fixed: '#261a00'
  on-primary-fixed-variant: '#5c4300'
  secondary-fixed: '#c4e7ff'
  secondary-fixed-dim: '#7bd0ff'
  on-secondary-fixed: '#001e2c'
  on-secondary-fixed-variant: '#004c69'
  tertiary-fixed: '#ffdadb'
  tertiary-fixed-dim: '#ffb2b7'
  on-tertiary-fixed: '#40000d'
  on-tertiary-fixed-variant: '#92002a'
  background: '#0b1326'
  on-background: '#dae2fd'
  surface-variant: '#2d3449'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '800'
    lineHeight: 56px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '800'
    lineHeight: 42px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-lg:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
  mono-data:
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
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  3xl: 64px
  grid_columns: '12'
  grid_gutter: 24px
  grid_margin: 32px
---

## Brand & Style

This design system is engineered for high-stakes financial environments where clarity, speed, and precision are paramount. The brand personality is **authoritative, institutional-grade, and energetic**, utilizing a high-contrast palette to ensure critical data is immediately legible.

The aesthetic direction is **Modern Minimalism with a Tech-Brutalist edge**. It avoids decorative flourishes like heavy gradients or soft shadows in favor of structural integrity, clear boundaries, and aggressive information hierarchy. It evokes a sense of "Mission Control" for personal or enterprise wealth management—utilizing deep matte surfaces to reduce eye strain and vibrant golden accents to draw focus to primary actions.

## Colors

The palette is optimized for a dark-mode-first experience, maximizing the luminous quality of the primary yellow against a matte black foundation.

- **Primary (Golden Yellow):** Reserved exclusively for primary actions, success highlights, and critical data points. It must maintain a high contrast ratio against the matte black surface.
- **Surface (Matte Black):** The base layer of the application, providing a non-reflective, deep background that allows foreground elements to "pop."
- **Surface Container (Dark Gray):** Used for cards, navigation bars, and tiered layouts to create subtle depth without relying on shadows.
- **Status Colors:** Success (Green) and Error (Red) are highly saturated. These should be used for price movements, validation states, and system alerts.

## Typography

This design system uses **Inter** exclusively to maintain a clean, systematic, and utilitarian appearance. 

- **Weight Strategy:** Headlines use ExtraBold (800) or Bold (700) to create a clear visual anchor. Body text uses Regular (400) for maximum readability in data-heavy views.
- **Numeric Data:** For financial figures, always enable **Tabular Figures** (`tnum`) to ensure numbers align vertically in tables and ledgers.
- **Micro-copy:** Small labels should use uppercase with slight tracking (letter spacing) to maintain legibility at 12px.

## Layout & Spacing

The layout follows a **Rigid Grid System** to communicate stability and professional organization.

- **Grid Model:** A 12-column fluid grid is used for desktop, scaling down to 4 columns for mobile. 
- **Spacing Logic:** An 8pt spatial system is employed for large layout shifts, while a 4pt "half-step" is used for tight component internals (e.g., icon-to-label spacing).
- **Density:** The system defaults to "High Density." Padding in data tables and lists should be compact to allow for maximum information visibility without scrolling.

## Elevation & Depth

To maintain an "Institutional" feel, this design system rejects soft, ambient shadows. Depth is communicated through **Tonal Layering and Borders**.

- **Level 0 (Surface):** Matte Black (#0f172a). Used for the main background.
- **Level 1 (Container):** Dark Gray (#1e293b). Used for primary content cards and navigation.
- **Level 2 (Inlay):** A slightly lighter gray or a 1px solid border (#334155). Used for nested elements like input fields or inner segments.
- **Borders:** Instead of shadows, use 1px solid strokes to define boundaries. Use `#fbbf24` (Primary) for active states and `#334155` for inactive/default states.

## Shapes

The shape language is **geometric and precise**. 

- **Corner Radius:** A universal 4px radius (`rounded-sm`) is applied to buttons, inputs, and cards. This provides a "technical" feel—softer than a sharp 90-degree angle but firm enough to look professional.
- **Interactive Elements:** Buttons and inputs share the same height and corner radius to maintain a consistent horizontal rhythm across forms.

## Components

- **Buttons:** 
  - **Primary:** Solid #fbbf24 background with #000000 text. Bold weight. No shadow.
  - **Secondary:** 1px border of #fbbf24 with #fbbf24 text. Transparent background.
- **Input Fields:** Deep matte background (#0f172a) with a 1px border (#334155). On focus, the border changes to Primary Yellow. Text is white or high-contrast gray.
- **Chips/Badges:** Used for status. For "Success," use a dark green background with bright green text. For "Error," use a dark red background with bright red text. Keep padding tight (4px top/bottom, 8px left/right).
- **Cards:** Use Surface Container (#1e293b) with no shadow. For interactive cards, add a 1px border that brightens on hover.
- **Data Tables:** High density. Row separators use #334155 at 0.5px or 1px thickness. Header labels should be uppercase `label-sm`.
- **Progress Indicators:** Use the Primary Yellow for active progress and a dark gray for the track. No rounded caps; use sharp/squared ends for a more technical look.