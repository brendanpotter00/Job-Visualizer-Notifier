import { Button } from '@mui/material';
import SyncAltIcon from '@mui/icons-material/SyncAlt';

export interface SyncFiltersButtonProps {
  direction: 'toList' | 'toGraph';
  onClick: () => void;
}

/**
 * Button for syncing filters between graph and list views
 */
export function SyncFiltersButton({ direction, onClick }: SyncFiltersButtonProps) {
  const label = direction === 'toList' ? 'Sync to List' : 'Sync to Graph';

  return (
    <Button
      variant="outlined"
      size="medium"
      startIcon={<SyncAltIcon />}
      onClick={onClick}
      sx={{ ml: 'auto' }}
    >
      {label}
    </Button>
  );
}
