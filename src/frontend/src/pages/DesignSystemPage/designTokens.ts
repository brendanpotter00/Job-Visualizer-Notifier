/**
 * Design tokens from the "One Second Sweet" design system (design.md).
 * All values are hardcoded from the design specification.
 */

// ─── Font Families ───────────────────────────────────────────────────────────

export const DS_FONT_FAMILY = {
  primary: '"Inter", -apple-system, system-ui, "Segoe UI", Helvetica, "Apple Color Emoji", Arial, sans-serif',
  mono: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
} as const;

// ─── Colors ──────────────────────────────────────────────────────────────────

interface ColorEntry {
  name: string;
  hex: string;
  description: string;
}

interface ColorGroup {
  groupName: string;
  colors: ColorEntry[];
}

export const DS_COLORS: ColorGroup[] = [
  {
    groupName: 'Primary',
    colors: [
      { name: 'Sweet Dark', hex: '#26251e', description: 'Primary text, headings, dark UI surfaces' },
      { name: 'Sweet Cream', hex: '#f2f1ed', description: 'Page background, primary surface' },
      { name: 'Sweet Light', hex: '#e6e5e0', description: 'Secondary surface, button backgrounds' },
      { name: 'Pure White', hex: '#ffffff', description: 'Maximum contrast elements' },
      { name: 'True Black', hex: '#000000', description: 'Minimal use, code/console contexts' },
    ],
  },
  {
    groupName: 'Accent',
    colors: [
      { name: 'Sweet Orange', hex: '#f54e00', description: 'Brand accent, primary CTAs, active links' },
      { name: 'Gold', hex: '#c08532', description: 'Secondary accent, premium contexts' },
    ],
  },
  {
    groupName: 'Semantic',
    colors: [
      { name: 'Error', hex: '#cf2d56', description: 'Warm crimson-rose error state' },
      { name: 'Success', hex: '#1f8a65', description: 'Muted teal-green success' },
    ],
  },
  {
    groupName: 'Timeline / Feature',
    colors: [
      { name: 'Thinking', hex: '#dfa88f', description: 'Warm peach for loading/thinking' },
      { name: 'Grep', hex: '#9fc9a2', description: 'Soft sage green for search' },
      { name: 'Read', hex: '#9fbbe0', description: 'Soft blue for data reading' },
      { name: 'Edit', hex: '#c0a8dd', description: 'Soft lavender for editing' },
    ],
  },
  {
    groupName: 'Surface Scale',
    colors: [
      { name: 'Surface 100', hex: '#f7f7f4', description: 'Lightest button/card surface' },
      { name: 'Surface 200', hex: '#f2f1ed', description: 'Primary page background' },
      { name: 'Surface 300', hex: '#ebeae5', description: 'Button default background' },
      { name: 'Surface 400', hex: '#e6e5e0', description: 'Card backgrounds, secondary surfaces' },
      { name: 'Surface 500', hex: '#e1e0db', description: 'Tertiary button, deeper emphasis' },
    ],
  },
  {
    groupName: 'Border',
    colors: [
      { name: 'Border Primary', hex: 'rgba(38, 37, 30, 0.1)', description: '10% warm brown (oklab fallback)' },
      { name: 'Border Medium', hex: 'rgba(38, 37, 30, 0.2)', description: '20% warm brown (oklab fallback)' },
      { name: 'Border Strong', hex: 'rgba(38, 37, 30, 0.55)', description: 'Strong borders, table rules' },
      { name: 'Border Solid', hex: '#26251e', description: 'Full-opacity dark border' },
      { name: 'Border Light', hex: '#f2f1ed', description: 'Light border matching page bg' },
    ],
  },
];

// ─── Typography ──────────────────────────────────────────────────────────────

interface TypographyRole {
  role: string;
  size: string;
  sizePx: number;
  weight: number;
  lineHeight: number;
  letterSpacing: string;
  notes: string;
}

export const DS_TYPOGRAPHY: TypographyRole[] = [
  { role: 'Display Hero', size: '4.00rem', sizePx: 64, weight: 700, lineHeight: 1.0, letterSpacing: '-2.125px', notes: 'Maximum compression, hero statements' },
  { role: 'Display Secondary', size: '3.38rem', sizePx: 54, weight: 700, lineHeight: 1.04, letterSpacing: '-1.875px', notes: 'Secondary hero, feature headlines' },
  { role: 'Section Heading', size: '3.00rem', sizePx: 48, weight: 700, lineHeight: 1.0, letterSpacing: '-1.5px', notes: 'Feature section titles' },
  { role: 'Sub-heading Large', size: '2.50rem', sizePx: 40, weight: 700, lineHeight: 1.5, letterSpacing: 'normal', notes: 'Card headings, feature sub-sections' },
  { role: 'Sub-heading', size: '1.63rem', sizePx: 26, weight: 700, lineHeight: 1.23, letterSpacing: '-0.625px', notes: 'Section sub-titles' },
  { role: 'Card Title', size: '1.38rem', sizePx: 22, weight: 700, lineHeight: 1.27, letterSpacing: '-0.25px', notes: 'Feature cards, list titles' },
  { role: 'Body Large', size: '1.25rem', sizePx: 20, weight: 600, lineHeight: 1.4, letterSpacing: '-0.125px', notes: 'Introductions, descriptions' },
  { role: 'Body', size: '1.00rem', sizePx: 16, weight: 400, lineHeight: 1.5, letterSpacing: 'normal', notes: 'Standard reading text' },
  { role: 'Body Medium', size: '1.00rem', sizePx: 16, weight: 500, lineHeight: 1.5, letterSpacing: 'normal', notes: 'Navigation, emphasized UI text' },
  { role: 'Body Semibold', size: '1.00rem', sizePx: 16, weight: 600, lineHeight: 1.5, letterSpacing: 'normal', notes: 'Strong labels, active states' },
  { role: 'Nav / Button', size: '0.94rem', sizePx: 15, weight: 600, lineHeight: 1.33, letterSpacing: 'normal', notes: 'Navigation links, button text' },
  { role: 'Caption', size: '0.88rem', sizePx: 14, weight: 500, lineHeight: 1.43, letterSpacing: 'normal', notes: 'Metadata, secondary labels' },
  { role: 'Caption Light', size: '0.88rem', sizePx: 14, weight: 400, lineHeight: 1.43, letterSpacing: 'normal', notes: 'Body captions, descriptions' },
  { role: 'Badge', size: '0.75rem', sizePx: 12, weight: 600, lineHeight: 1.33, letterSpacing: '0.125px', notes: 'Pill badges, tags, status labels' },
  { role: 'Micro Label', size: '0.75rem', sizePx: 12, weight: 400, lineHeight: 1.33, letterSpacing: '0.125px', notes: 'Small metadata, timestamps' },
  { role: 'Mono Body', size: '0.75rem', sizePx: 12, weight: 400, lineHeight: 1.67, letterSpacing: 'normal', notes: 'Code blocks (monospace)' },
];

// ─── Spacing ─────────────────────────────────────────────────────────────────

interface SpacingEntry {
  label: string;
  value: number;
}

export const DS_SPACING_FINE: SpacingEntry[] = [
  { label: '1.5px', value: 1.5 },
  { label: '2px', value: 2 },
  { label: '2.5px', value: 2.5 },
  { label: '3px', value: 3 },
  { label: '4px', value: 4 },
  { label: '5px', value: 5 },
  { label: '6px', value: 6 },
];

export const DS_SPACING_STANDARD: SpacingEntry[] = [
  { label: '8px', value: 8 },
  { label: '10px', value: 10 },
  { label: '12px', value: 12 },
  { label: '14px', value: 14 },
  { label: '16px', value: 16 },
  { label: '24px', value: 24 },
  { label: '32px', value: 32 },
  { label: '48px', value: 48 },
  { label: '64px', value: 64 },
  { label: '96px', value: 96 },
];

// ─── Border Radius ───────────────────────────────────────────────────────────

interface BorderRadiusEntry {
  label: string;
  name: string;
  value: string;
}

export const DS_BORDER_RADIUS: BorderRadiusEntry[] = [
  { label: '1.5px', name: 'Micro', value: '1.5px' },
  { label: '2px', name: 'Small', value: '2px' },
  { label: '3px', name: 'Medium', value: '3px' },
  { label: '4px', name: 'Standard', value: '4px' },
  { label: '8px', name: 'Comfortable', value: '8px' },
  { label: '10px', name: 'Featured', value: '10px' },
  { label: '9999px', name: 'Full Pill', value: '9999px' },
];

// ─── Elevation ───────────────────────────────────────────────────────────────

interface ElevationLevel {
  level: number;
  name: string;
  boxShadow: string;
  description: string;
}

export const DS_ELEVATION: ElevationLevel[] = [
  { level: 0, name: 'Flat', boxShadow: 'none', description: 'Page background, text blocks' },
  { level: 1, name: 'Border Ring', boxShadow: 'rgba(38, 37, 30, 0.1) 0px 0px 0px 1px', description: 'Standard card/container border' },
  { level: 2, name: 'Border Medium', boxShadow: 'rgba(38, 37, 30, 0.2) 0px 0px 0px 1px', description: 'Emphasized borders, active states' },
  { level: 3, name: 'Ambient', boxShadow: 'rgba(0,0,0,0.02) 0px 0px 16px, rgba(0,0,0,0.008) 0px 0px 8px', description: 'Floating elements, subtle glow' },
  { level: 4, name: 'Elevated Card', boxShadow: 'rgba(0,0,0,0.14) 0px 28px 70px, rgba(0,0,0,0.1) 0px 14px 32px, rgba(38, 37, 30, 0.1) 0px 0px 0px 1px', description: 'Modals, popovers, elevated cards' },
  { level: 5, name: 'Focus', boxShadow: 'rgba(0,0,0,0.1) 0px 4px 12px', description: 'Interactive focus feedback' },
];

// ─── Button Variants ─────────────────────────────────────────────────────────

interface ButtonVariant {
  name: string;
  bg: string;
  text: string;
  fontSize: string;
  fontWeight: number;
  padding: string;
  borderRadius: string;
  hoverText: string;
  description: string;
}

export const DS_BUTTONS: ButtonVariant[] = [
  {
    name: 'Primary',
    bg: '#ebeae5',
    text: '#26251e',
    fontSize: '15px',
    fontWeight: 600,
    padding: '10px 14px',
    borderRadius: '8px',
    hoverText: '#cf2d56',
    description: 'Primary actions, main CTAs',
  },
  {
    name: 'Secondary Pill',
    bg: '#e6e5e0',
    text: 'rgba(38, 37, 30, 0.6)',
    fontSize: '14px',
    fontWeight: 500,
    padding: '3px 8px',
    borderRadius: '9999px',
    hoverText: '#cf2d56',
    description: 'Tags, filters, secondary actions',
  },
  {
    name: 'Tertiary Pill',
    bg: '#e1e0db',
    text: 'rgba(38, 37, 30, 0.6)',
    fontSize: '14px',
    fontWeight: 500,
    padding: '3px 8px',
    borderRadius: '9999px',
    hoverText: '#cf2d56',
    description: 'Active filter state, selected tags',
  },
  {
    name: 'Ghost',
    bg: 'rgba(38, 37, 30, 0.06)',
    text: 'rgba(38, 37, 30, 0.55)',
    fontSize: '14px',
    fontWeight: 500,
    padding: '6px 12px',
    borderRadius: '8px',
    hoverText: '#cf2d56',
    description: 'Tertiary actions, dismiss buttons',
  },
  {
    name: 'Light Surface',
    bg: '#f7f7f4',
    text: '#26251e',
    fontSize: '14px',
    fontWeight: 500,
    padding: '0px 12px',
    borderRadius: '8px',
    hoverText: '#cf2d56',
    description: 'Dropdown triggers, subtle elements',
  },
];
