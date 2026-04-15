# One Second Sweet Design Doc

A curated design system merging Cursor's warm visual identity with Notion's typographic clarity. Cursor provides the colors, borders, shadows, components, layout, depth, and motion. Notion provides the typography: NotionInter as a single, weight-differentiated font family replacing Cursor's three-font system.

## 1. Visual Theme & Atmosphere

The entire experience is built on a warm off-white canvas (`#f2f1ed`) with dark warm-brown text (`#26251e`) -- not pure black, not neutral gray, but a deeply warm near-black with a yellowish undertone that evokes old paper, ink, and craft. This warmth permeates every surface: backgrounds lean toward cream (`#e6e5e0`, `#ebeae5`), borders dissolve into transparent warm overlays using `oklab` color space, and even the error state (`#cf2d56`) carries warmth rather than clinical red. The result feels more like a premium print publication than a tech website.

NotionInter (a modified Inter) is the sole typographic voice -- a clean, modern sans-serif with aggressive negative letter-spacing at display sizes (-2.125px at 64px) that creates compressed, precise headlines. Rather than switching between fonts for different contexts, the system uses four weights to create hierarchy: 700 for display headings, 600 for emphasis and navigation, 500 for UI elements, and 400 for body reading text. OpenType features `"lnum"` (lining numerals) and `"locl"` (localized forms) add sophistication at larger sizes. For code contexts, a standard monospace fallback stack maintains technical clarity.

The border system is particularly distinctive -- `oklab()` color space applies warm brown at various alpha levels (0.1, 0.2, 0.55) to create borders that feel organic rather than mechanical. The signature border color `oklab(0.263084 -0.00230259 0.0124794 / 0.1)` is a perceptually uniform color that maintains visual consistency across different backgrounds.

**Key Characteristics:**
- NotionInter with aggressive negative letter-spacing (-2.125px at 64px, -1.875px at 54px, -1.5px at 48px) for compressed display headings
- Four-weight hierarchy: 400 (body), 500 (UI), 600 (emphasis), 700 (display)
- Warm off-white background (`#f2f1ed`) instead of pure white -- the entire system is warm-shifted
- Primary text color `#26251e` (warm near-black with yellow undertone)
- Accent orange `#f54e00` for brand highlight and links
- oklab-space borders at various alpha levels for perceptually uniform edge treatment
- Pill-shaped elements with extreme radius (9999px, full-pill)
- 8px base spacing system with fine-grained sub-8px increments (1.5px, 2px, 2.5px, 3px, 4px, 5px, 6px)

## 2. Color Palette & Roles

### Primary
- **Sweet Dark** (`#26251e`): Primary text, headings, dark UI surfaces. A warm near-black with distinct yellow-brown undertone -- the defining color of the system.
- **Sweet Cream** (`#f2f1ed`): Page background, primary surface. Not white but a warm cream that sets the entire warm tone.
- **Sweet Light** (`#e6e5e0`): Secondary surface, button backgrounds, card fills. A slightly warmer, slightly darker cream.
- **Pure White** (`#ffffff`): Used sparingly for maximum contrast elements and specific surface highlights.
- **True Black** (`#000000`): Minimal use, specific code/console contexts.

### Accent
- **Sweet Orange** (`#f54e00`): Brand accent, `--color-accent`. A vibrant red-orange used for primary CTAs, active links, and brand moments. Warm and urgent.
- **Gold** (`#c08532`): Secondary accent, warm gold for premium or highlighted contexts.

### Semantic
- **Error** (`#cf2d56`): `--color-error`. A warm crimson-rose rather than cold red.
- **Success** (`#1f8a65`): `--color-success`. A muted teal-green, warm-shifted.

### Timeline / Feature Colors
- **Thinking** (`#dfa88f`): Warm peach for loading/thinking states.
- **Grep** (`#9fc9a2`): Soft sage green for search operations.
- **Read** (`#9fbbe0`): Soft blue for data reading operations.
- **Edit** (`#c0a8dd`): Soft lavender for editing operations.

### Surface Scale
- **Surface 100** (`#f7f7f4`): Lightest button/card surface, barely tinted.
- **Surface 200** (`#f2f1ed`): Primary page background.
- **Surface 300** (`#ebeae5`): Button default background, subtle emphasis.
- **Surface 400** (`#e6e5e0`): Card backgrounds, secondary surfaces.
- **Surface 500** (`#e1e0db`): Tertiary button background, deeper emphasis.

### Border Colors
- **Border Primary** (`oklab(0.263084 -0.00230259 0.0124794 / 0.1)`): Standard border, 10% warm brown in oklab space.
- **Border Medium** (`oklab(0.263084 -0.00230259 0.0124794 / 0.2)`): Emphasized border, 20% warm brown.
- **Border Strong** (`rgba(38, 37, 30, 0.55)`): Strong borders, table rules.
- **Border Solid** (`#26251e`): Full-opacity dark border for maximum contrast.
- **Border Light** (`#f2f1ed`): Light border matching page background.

### Shadows & Depth
- **Card Shadow** (`rgba(0,0,0,0.14) 0px 28px 70px, rgba(0,0,0,0.1) 0px 14px 32px, oklab(0.263084 -0.00230259 0.0124794 / 0.1) 0px 0px 0px 1px`): Heavy elevated card with warm oklab border ring.
- **Ambient Shadow** (`rgba(0,0,0,0.02) 0px 0px 16px, rgba(0,0,0,0.008) 0px 0px 8px`): Subtle ambient glow for floating elements.

## 3. Typography Rules

### Font Family
- **Primary (all contexts)**: `NotionInter`, with fallbacks: `Inter, -apple-system, system-ui, Segoe UI, Helvetica, Apple Color Emoji, Arial, sans-serif`
- **Code/Technical**: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace`
- **OpenType Features**: `"lnum"` (lining numerals) and `"locl"` (localized forms) enabled on display and heading text

### Hierarchy

| Role | Size | Weight | Line Height | Letter Spacing | Notes |
|------|------|--------|-------------|----------------|-------|
| Display Hero | 64px (4.00rem) | 700 | 1.00 (tight) | -2.125px | Maximum compression, hero statements |
| Display Secondary | 54px (3.38rem) | 700 | 1.04 (tight) | -1.875px | Secondary hero, feature headlines |
| Section Heading | 48px (3.00rem) | 700 | 1.00 (tight) | -1.5px | Feature section titles, with `"lnum"` |
| Sub-heading Large | 40px (2.50rem) | 700 | 1.50 | normal | Card headings, feature sub-sections |
| Sub-heading | 26px (1.63rem) | 700 | 1.23 (tight) | -0.625px | Section sub-titles, content headers |
| Card Title | 22px (1.38rem) | 700 | 1.27 (tight) | -0.25px | Feature cards, list titles |
| Body Large | 20px (1.25rem) | 600 | 1.40 | -0.125px | Introductions, feature descriptions |
| Body | 16px (1.00rem) | 400 | 1.50 | normal | Standard reading text |
| Body Medium | 16px (1.00rem) | 500 | 1.50 | normal | Navigation, emphasized UI text |
| Body Semibold | 16px (1.00rem) | 600 | 1.50 | normal | Strong labels, active states |
| Nav / Button | 15px (0.94rem) | 600 | 1.33 | normal | Navigation links, button text |
| Caption | 14px (0.88rem) | 500 | 1.43 | normal | Metadata, secondary labels |
| Caption Light | 14px (0.88rem) | 400 | 1.43 | normal | Body captions, descriptions |
| Badge | 12px (0.75rem) | 600 | 1.33 | 0.125px | Pill badges, tags, status labels |
| Micro Label | 12px (0.75rem) | 400 | 1.33 | 0.125px | Small metadata, timestamps |
| Mono Body | 12px (0.75rem) | 400 | 1.67 (relaxed) | normal | Code blocks (monospace stack) |
| Mono Small | 11px (0.69rem) | 400 | 1.33 | -0.275px | Inline code, terminal (monospace stack) |

### Principles
- **Compression at scale**: NotionInter at display sizes uses -2.125px letter-spacing at 64px, progressively relaxing to -0.625px at 26px and normal at 16px. The compression creates density at headlines while maintaining readability at body sizes.
- **Four-weight hierarchy**: 400 (body/reading), 500 (UI/interactive), 600 (emphasis/navigation), 700 (headings/display). Weight differentiation replaces font-family switching for hierarchy.
- **Warm scaling**: Line height tightens as size increases -- 1.50 at body (16px), 1.23-1.27 at sub-headings, 1.00-1.04 at display. This creates denser, more impactful headlines.
- **Badge micro-tracking**: The 12px badge text uses positive letter-spacing (+0.125px) -- the only positive tracking in the system, creating wider, more legible small text.
- **Weight restraint at body**: Body text stays at 400, relying on the warm color system and spacing for hierarchy rather than weight. Heavier weights are reserved for navigation (600) and headings (700).

## 4. Component Stylings

### Buttons

**Primary (Warm Surface)**
- Background: `#ebeae5` (Surface 300)
- Text: `#26251e` (Sweet Dark)
- Font: NotionInter 15px weight 600
- Padding: 10px 12px 10px 14px
- Radius: 8px
- Outline: none
- Hover: text shifts to `var(--color-error)` (`#cf2d56`)
- Focus shadow: `rgba(0,0,0,0.1) 0px 4px 12px`
- Use: Primary actions, main CTAs

**Secondary Pill**
- Background: `#e6e5e0` (Surface 400)
- Text: `oklab(0.263 / 0.6)` (60% warm brown)
- Font: NotionInter 14px weight 500
- Padding: 3px 8px
- Radius: full pill (9999px)
- Hover: text shifts to `var(--color-error)`
- Use: Tags, filters, secondary actions

**Tertiary Pill**
- Background: `#e1e0db` (Surface 500)
- Text: `oklab(0.263 / 0.6)` (60% warm brown)
- Font: NotionInter 14px weight 500
- Radius: full pill
- Use: Active filter state, selected tags

**Ghost (Transparent)**
- Background: `rgba(38, 37, 30, 0.06)` (6% warm brown)
- Text: `rgba(38, 37, 30, 0.55)` (55% warm brown)
- Font: NotionInter 14px weight 500
- Padding: 6px 12px
- Use: Tertiary actions, dismiss buttons

**Light Surface**
- Background: `#f7f7f4` (Surface 100) or `#f2f1ed` (Surface 200)
- Text: `#26251e` or `oklab(0.263 / 0.9)` (90%)
- Font: NotionInter 14px weight 500
- Padding: 0px 8px 1px 12px
- Use: Dropdown triggers, subtle interactive elements

### Cards & Containers
- Background: `#e6e5e0` or `#f2f1ed`
- Border: `1px solid oklab(0.263 / 0.1)` (warm brown at 10%)
- Radius: 8px (standard), 4px (compact), 10px (featured)
- Shadow: `rgba(0,0,0,0.14) 0px 28px 70px, rgba(0,0,0,0.1) 0px 14px 32px` for elevated cards
- Title: NotionInter 22px weight 700, letter-spacing -0.25px
- Body: NotionInter 16px weight 400, color `rgba(38, 37, 30, 0.55)`
- Hover: shadow intensification

### Inputs & Forms
- Background: transparent or surface
- Text: `#26251e`, NotionInter 16px weight 400
- Padding: 8px 8px 6px (textarea)
- Border: `1px solid oklab(0.263 / 0.1)`
- Focus: border shifts to `oklab(0.263 / 0.2)` or accent orange
- Placeholder: NotionInter 16px weight 400, color `rgba(38, 37, 30, 0.4)`

### Navigation
- Clean horizontal nav on warm cream background
- Logo/wordmark left-aligned
- Links: NotionInter 15px weight 600, color `#26251e`
- CTA button: warm surface with Sweet Dark text
- Tab navigation: bottom border `1px solid oklab(0.263 / 0.1)` with active tab differentiation

### Distinctive Components

**Status Timeline**
- Vertical timeline showing operations: thinking (peach `#dfa88f`), grep (sage `#9fc9a2`), read (blue `#9fbbe0`), edit (lavender `#c0a8dd`)
- Each step uses its semantic color with matching text
- Labels: NotionInter 14px weight 500
- Descriptions: NotionInter 16px weight 400
- Connected with vertical lines in `rgba(38, 37, 30, 0.1)`

**Pill Badges**
- Background: tinted with semantic color at 15% opacity
- Text: full semantic color
- Font: NotionInter 12px weight 600, letter-spacing +0.125px
- Padding: 4px 8px
- Radius: 9999px (full pill)

**Code Blocks**
- Font: monospace fallback stack, 12px weight 400, line-height 1.67
- Background: `#26251e` (Sweet Dark) or `#f7f7f4` (Surface 100) for inline
- Border: `1px solid oklab(0.263 / 0.1)`
- Radius: 8px (block), 3px (inline)

## 5. Layout Principles

### Spacing System
- Base unit: 8px
- Fine scale: 1.5px, 2px, 2.5px, 3px, 4px, 5px, 6px (sub-8px for micro-adjustments)
- Standard scale: 8px, 10px, 12px, 14px
- Extended scale: 16px, 24px, 32px, 48px, 64px, 96px
- Notable: fine-grained sub-8px increments for precise icon/text alignment

### Grid & Container
- Max content width: approximately 1200px
- Hero: centered single-column with generous top padding (80-120px)
- Feature sections: 2-3 column grids for cards and features
- Full-width sections with warm cream or slightly darker backgrounds
- Sidebar layouts for documentation and settings pages

### Whitespace Philosophy
- **Warm negative space**: The cream background means whitespace has warmth and texture, unlike cold white minimalism. Large empty areas feel cozy rather than clinical.
- **Compressed text, open layout**: Aggressive negative letter-spacing on NotionInter headlines is balanced by generous surrounding margins. Text is dense; space around it breathes.
- **Section variation**: Alternating surface tones (cream -> lighter cream -> cream) create subtle section differentiation without harsh boundaries.

### Border Radius Scale
- Micro (1.5px): Fine detail elements
- Small (2px): Inline elements, code spans
- Medium (3px): Small containers, inline badges
- Standard (4px): Cards, images, compact buttons
- Comfortable (8px): Primary buttons, cards, menus
- Featured (10px): Larger containers, featured cards
- Full Pill (9999px): Pill buttons, tags, badges

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Flat (Level 0) | No shadow | Page background, text blocks |
| Border Ring (Level 1) | `oklab(0.263 / 0.1) 0px 0px 0px 1px` | Standard card/container border (warm oklab) |
| Border Medium (Level 1b) | `oklab(0.263 / 0.2) 0px 0px 0px 1px` | Emphasized borders, active states |
| Ambient (Level 2) | `rgba(0,0,0,0.02) 0px 0px 16px, rgba(0,0,0,0.008) 0px 0px 8px` | Floating elements, subtle glow |
| Elevated Card (Level 3) | `rgba(0,0,0,0.14) 0px 28px 70px, rgba(0,0,0,0.1) 0px 14px 32px, oklab ring` | Modals, popovers, elevated cards |
| Focus | `rgba(0,0,0,0.1) 0px 4px 12px` on button focus | Interactive focus feedback |

**Shadow Philosophy**: Borders use perceptually uniform oklab color space rather than rgba, ensuring warm brown borders look consistent across different background tones. Elevation shadows use dramatically large blur values (28px, 70px) with moderate opacity (0.14, 0.1), creating a diffused, atmospheric lift rather than hard-edged drop shadows. Cards don't feel like they float above the page -- they feel like the page has gently opened a space for them.

### Decorative Depth
- Warm cream surface variations create subtle tonal depth without shadows
- oklab borders at 10% and 20% create a spectrum of edge definition
- No harsh divider lines -- section separation through background tone shifts and spacing

## 7. Interaction & Motion

### Hover States
- Buttons: text color shifts to `--color-error` (`#cf2d56`) on hover -- a distinctive warm crimson that signals interactivity
- Links: color shift to accent orange (`#f54e00`) or underline decoration with `rgba(38, 37, 30, 0.4)`
- Cards: shadow intensification on hover (ambient -> elevated)

### Focus States
- Shadow-based focus: `rgba(0,0,0,0.1) 0px 4px 12px` for depth-based focus indication
- Border focus: `oklab(0.263 / 0.2)` (20% border) for input/form focus
- Consistent warm tone in all focus states -- no cold blue focus rings

### Transitions
- Color transitions: 150ms ease for text/background color changes
- Shadow transitions: 200ms ease for elevation changes
- Transform: subtle scale or translate for interactive feedback

## 8. Responsive Behavior

### Breakpoints
| Name | Width | Key Changes |
|------|-------|-------------|
| Mobile | <600px | Single column, reduced padding, stacked navigation |
| Tablet Small | 600-768px | 2-column grids begin |
| Tablet | 768-900px | Expanded card grids, sidebar appears |
| Desktop Small | 900-1279px | Full layout forming |
| Desktop | >1279px | Full layout, maximum content width |

### Touch Targets
- Buttons use comfortable padding (6px-14px vertical, 8px-14px horizontal)
- Pill buttons maintain tap-friendly sizing with 3px-10px padding
- Navigation links at 15px with adequate spacing for touch

### Collapsing Strategy
- Hero: 64px NotionInter 700 -> 40px -> 26px on smaller screens, maintaining proportional letter-spacing
- Navigation: horizontal links -> hamburger menu on mobile
- Feature cards: 3-column -> 2-column -> single column stacked
- Section spacing: 80px+ -> 48px -> 32px on mobile
- Timeline visualization: horizontal -> vertical stacking

### Image Behavior
- Screenshots with warm `1px solid oklab(0.263 / 0.1)` border treatment at all sizes
- Rounded corners: 8px standard
- Product screenshots use responsive images with consistent border radius
- Full-width hero images scale proportionally

## 9. Agent Prompt Guide

### Quick Color Reference
- Primary CTA background: `#ebeae5` (warm cream button)
- Page background: `#f2f1ed` (warm off-white)
- Text color: `#26251e` (warm near-black)
- Secondary text: `rgba(38, 37, 30, 0.55)` (55% warm brown)
- Accent: `#f54e00` (orange)
- Error/hover: `#cf2d56` (warm crimson)
- Success: `#1f8a65` (muted teal)
- Border: `oklab(0.263084 -0.00230259 0.0124794 / 0.1)` or `rgba(38, 37, 30, 0.1)` as fallback

### Quick Typography Reference
- Font: `NotionInter, Inter, -apple-system, system-ui, sans-serif`
- Code: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`
- Weights: 400 (body), 500 (UI), 600 (emphasis/nav), 700 (headings)
- Display tracking: -2.125px at 64px, -1.5px at 48px, -0.625px at 26px, normal at 16px

### Example Component Prompts
- "Create a hero section on `#f2f1ed` warm cream background. Headline at 64px NotionInter weight 700, line-height 1.00, letter-spacing -2.125px, color `#26251e`. Subtitle at 20px NotionInter weight 600, line-height 1.40, letter-spacing -0.125px, color `rgba(38,37,30,0.55)`. Primary CTA button (`#ebeae5` bg, 8px radius, 10px 14px padding, NotionInter 15px weight 600) with hover text shift to `#cf2d56`."
- "Design a card: `#e6e5e0` background, border `1px solid rgba(38,37,30,0.1)`. Radius 8px. Title at 22px NotionInter weight 700, letter-spacing -0.25px. Body at 16px NotionInter weight 400, color `rgba(38,37,30,0.55)`. Use `#f54e00` for link accents."
- "Build a pill tag: `#e6e5e0` background, `rgba(38,37,30,0.6)` text, full-pill radius (9999px), 3px 8px padding, 12px NotionInter weight 600, letter-spacing +0.125px."
- "Create navigation: sticky `#f2f1ed` background with backdrop-filter blur. NotionInter 15px weight 600 for links, `#26251e` text. CTA button right-aligned with `#ebeae5` bg and 8px radius. Bottom border `1px solid rgba(38,37,30,0.1)`."
- "Design a status timeline showing four steps: Thinking (`#dfa88f`), Search (`#9fc9a2`), Read (`#9fbbe0`), Edit (`#c0a8dd`). Each step: NotionInter 14px weight 500 label + 16px weight 400 description + vertical connecting line in `rgba(38,37,30,0.1)`."

### Iteration Guide
1. Always use warm tones -- `#f2f1ed` background, `#26251e` text, never pure white/black for primary surfaces
2. Letter-spacing scales with font size for NotionInter: -2.125px at 64px, -1.5px at 48px, -0.625px at 26px, normal at 16px
3. Use `rgba(38, 37, 30, alpha)` as a CSS-compatible fallback for oklab borders
4. One font, four weights: NotionInter 700 (display), 600 (emphasis/nav), 500 (UI), 400 (body). Monospace fallback stack for code.
5. Pill shapes (9999px radius) for tags and filters; 8px radius for primary buttons and cards
6. Hover states use `#cf2d56` text color -- the warm crimson shift is a signature interaction
7. Shadows use large blur values (28px, 70px) for diffused atmospheric depth
8. The sub-8px spacing scale (1.5, 2, 2.5, 3, 4, 5, 6px) is critical for icon/text micro-alignment
