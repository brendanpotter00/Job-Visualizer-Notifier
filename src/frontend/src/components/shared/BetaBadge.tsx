import { TextBadge } from './TextBadge';

/**
 * "BETA" beside a page heading.
 *
 * A thin wrapper since the same pill picked up a second caller (the "Custom"
 * marker on a user's own board in the company dropdown). All of the styling —
 * and the measured cap-height nudge that keeps an all-caps word optically
 * centred — now lives in {@link TextBadge}; this file exists so the two callers
 * of the Beta marker keep naming the concept rather than the shape.
 *
 * No `scale` prop, deliberately. One used to exist for a 16px sidebar nav row
 * and went away with the nav badge itself; `TextBadge` takes a `fontSize` for
 * callers that genuinely need one, and a page heading is always the default.
 */
export function BetaBadge() {
  return <TextBadge label="Beta" />;
}
