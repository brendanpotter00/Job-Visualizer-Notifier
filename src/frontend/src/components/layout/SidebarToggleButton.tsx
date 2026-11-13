import IconButton from '@mui/material/IconButton';
import SvgIcon, { type SvgIconProps } from '@mui/material/SvgIcon';
import Tooltip from '@mui/material/Tooltip';

export const APP_NAVIGATION_ID = 'app-navigation';

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
  open: boolean;
  onClick: () => void;
}

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
