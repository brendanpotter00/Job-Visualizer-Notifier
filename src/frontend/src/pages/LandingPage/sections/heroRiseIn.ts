const RISE_PX = 16;
const DURATION_MS = 750;
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
