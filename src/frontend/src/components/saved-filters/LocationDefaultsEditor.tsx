import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import { AsyncMultiSelectAutocomplete } from '../shared/filters/AsyncMultiSelectAutocomplete.tsx';

export interface LocationDefaultsEditorProps {
  locations: string[];
  onAdd: (location: string) => void;
  onRemove: (location: string) => void;
}

/**
 * One shared set of default locations, applied to BOTH the Recent Jobs and
 * Company Trends pages (unlike time windows, which are per-page). Options come
 * from the server-side location search.
 */
export function LocationDefaultsEditor({
  locations,
  onAdd,
  onRemove,
}: LocationDefaultsEditorProps) {
  return (
    <Paper sx={{ p: 4 }}>
      <Typography variant="h6" gutterBottom>
        Default locations
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Shared across both the Recent Jobs and Company Trends pages. Leave empty
        to see all locations.
      </Typography>

      <AsyncMultiSelectAutocomplete
        label="Locations"
        value={locations}
        onAdd={onAdd}
        onRemove={onRemove}
      />
    </Paper>
  );
}
