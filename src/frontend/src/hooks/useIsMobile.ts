import { useMediaQuery, useTheme } from '@mui/material';
import { MOBILE_BREAKPOINT } from '../config/responsive';

/**
 * Single source of truth for "is the viewport in the compact mobile layout?".
 * Returns true below {@link MOBILE_BREAKPOINT} (<600px). Use for props that take
 * a raw value rather than an sx breakpoint object (e.g. `CompanyLogo`'s numeric
 * `size`); for styles, prefer the responsive `{ xs, sm }` tokens in
 * `config/responsive.ts` directly in `sx`.
 */
export function useIsMobile(): boolean {
  const theme = useTheme();
  return useMediaQuery(theme.breakpoints.down(MOBILE_BREAKPOINT));
}
