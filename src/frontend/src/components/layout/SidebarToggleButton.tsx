import IconButton from '@mui/material/IconButton';
import SvgIcon, { type SvgIconProps } from '@mui/material/SvgIcon';
import Tooltip from '@mui/material/Tooltip';

/** `id` of the drawer content the toggle controls (for `aria-controls`). */
export const APP_NAVIGATION_ID = 'app-navigation';

/**
 * A window with a left-hand pane — the glyph desktop apps use for "sidebar".
 * Drawn here rather than borrowed from @mui/icons-material, whose closest
 * shapes put the pane on the right or read as a layout picker.
 */
export function SidebarIcon(props: SvgIconProps) {
  return (
    <SvgIcon {...props} viewBox="0 0 24 24">
      <rect
        x="3"
        y="4.75"
        width="18"
        height="14.5"
        rx="2.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path d="M9.25 4.75v14.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </SvgIcon>
  );
}

interface SidebarToggleButtonProps {
  /** Whether the sidebar is currently open. */
  open: boolean;
  onClick: () => void;
}

/**
 * The one sidebar toggle, rendered at the start of the full-width app bar on
 * every breakpoint. The drawer (permanent on desktop, an overlay on mobile)
 * opens and closes beneath the bar, so the toggle never travels with the
 * drawer edge.
 *
 * The accessible name is stable and `aria-expanded` carries the state; the
 * tooltip says what a click will do.
 */
export function SidebarToggleButton({ open, onClick }: SidebarToggleButtonProps) {
  return (
    <Tooltip title={open ? 'Hide sidebar' : 'Show sidebar'} enterDelay={400} describeChild>
      <IconButton
        color="inherit"
        edge="start"
        aria-label="Toggle sidebar"
        aria-expanded={open}
        aria-controls={APP_NAVIGATION_ID}
        onClick={onClick}
      >
        <SidebarIcon />
      </IconButton>
    </Tooltip>
  );
}
