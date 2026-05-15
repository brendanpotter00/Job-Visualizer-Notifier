/**
 * Page-scoped design tokens for the admin ops-console aesthetic.
 *
 * These tokens deliberately live outside the global MUI theme so admin pages
 * can carry a distinct visual identity (dark slate + monospace) without
 * dragging the rest of the app into the same look. The MUI shell (AppBar,
 * NavigationDrawer) keeps the existing monochrome theme.
 */

export const OPS = {
  // Deep slate background, lighter slate for cards. Pure black reads as a
  // bug to most users; #0b1018 still feels "dark" but admits color.
  bg: '#0b1018',
  surface: '#11182a',
  surfaceAlt: '#0d1422',
  border: '#1f2a3d',
  borderStrong: '#324158',

  // Text scale: warm white for primary, cool muted for body, very dim for
  // separator copy. The contrast jumps deliberately — there's no in-between.
  textPrimary: '#e8edf5',
  textMuted: '#8896ad',
  textDim: '#4a5872',

  // Single amber accent for "live" and counts; green for positive deltas;
  // red reserved for admins/destructive callouts. No purple anywhere — that's
  // generic-AI signature.
  accent: '#fbbf24',
  accentDim: '#7a5a10',
  positive: '#34d399',
  adminBadge: '#f87171',

  // Monospace stack: "Infra Mono" is preloaded in index.html via fontshare.
  // Fallbacks cover platform-mono and the generic family.
  mono: '"Infra Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  sans: 'Helvetica, Arial, sans-serif',
} as const;

export const SX = {
  page: {
    minHeight: 'calc(100vh - 64px)',
    bgcolor: OPS.bg,
    color: OPS.textPrimary,
    fontFamily: OPS.mono,
    px: { xs: 2, sm: 4, md: 5 },
    py: { xs: 3, md: 4 },
    // Faint radial-grid pattern. Anchors the page in a way that solid black
    // can't. Opacity is low enough that it never competes with content.
    backgroundImage:
      'radial-gradient(rgba(255,255,255,0.035) 1px, transparent 1px)',
    backgroundSize: '22px 22px',
  },
  surface: {
    bgcolor: OPS.surface,
    border: `1px solid ${OPS.border}`,
    borderRadius: 0,
    color: OPS.textPrimary,
  },
  surfaceAlt: {
    bgcolor: OPS.surfaceAlt,
    border: `1px solid ${OPS.border}`,
    borderRadius: 0,
  },
  caption: {
    fontFamily: OPS.mono,
    fontSize: 10.5,
    letterSpacing: '0.22em',
    textTransform: 'uppercase',
    color: OPS.textMuted,
    fontWeight: 700,
  },
  dimMono: {
    fontFamily: OPS.mono,
    fontSize: 12,
    color: OPS.textMuted,
  },
} as const;
