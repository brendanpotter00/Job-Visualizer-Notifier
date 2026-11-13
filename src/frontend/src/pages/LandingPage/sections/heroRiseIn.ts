/**
 * The hero's entrance: the headline, then the CTAs, rise ~16px and fade in once
 * on load (owner request, 2026-11-12 — "text should fade in from the bottom
 * up"; hero only, subtle). Nothing else on the page animates in.
 *
 * CSS keyframes rather than framer-motion: it must fire on MOUNT and never
 * again, it needs no JS before first paint (the h1 is the page's LCP element),
 * and `both` holds the start frame through the stagger delay so the buttons
 * never flash in before their fade. Same pattern as DiscoveryNetworkLog's
 * ROW_ANIMATION. Reduced motion gets the end state with no movement.
 */

/** Rise distance (px) — enough to read as "from below", small enough to stay quiet. */
const RISE_PX = 16;
/** Duration (ms). */
const DURATION_MS = 750;
/** Delay between the headline and the CTAs (ms). */
export const HERO_RISE_STAGGER_MS = 180;

export function heroRiseIn(delayMs = 0) {
  return {
    '@keyframes landingHeroRiseIn': {
      from: { opacity: 0, transform: `translateY(${RISE_PX}px)` },
      to: { opacity: 1, transform: 'none' },
    },
    animation: `landingHeroRiseIn ${DURATION_MS}ms cubic-bezier(0.22, 1, 0.36, 1) ${delayMs}ms both`,
    '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
  } as const;
}
