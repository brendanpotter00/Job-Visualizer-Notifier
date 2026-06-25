import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Typography from '@mui/material/Typography';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { AsyncMultiSelectAutocomplete } from '../shared/filters/AsyncMultiSelectAutocomplete.tsx';
import { SectionSaveButton } from './SectionSaveButton.tsx';

export interface LocationDefaultsEditorProps {
  locations: string[];
  onAdd: (location: string) => void;
  onRemove: (location: string) => void;
  /** Section-save state/handlers (the per-section Save button). */
  dirty: boolean;
  saving: boolean;
  success: boolean;
  error: string | null;
  onSave: () => void;
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
  dirty,
  saving,
  success,
  error,
  onSave,
}: LocationDefaultsEditorProps) {
  return (
    <Accordion
      defaultExpanded
      disableGutters
      sx={{
        borderRadius: 1,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 4, py: 1 }}>
        <Typography variant="h6">Default locations</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 4, pb: 4, pt: 0 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Shared across both the Recent Jobs and Company Trends pages. Leave empty to see all
          locations.
        </Typography>

        <AsyncMultiSelectAutocomplete
          label="Locations"
          value={locations}
          onAdd={onAdd}
          onRemove={onRemove}
        />

        <SectionSaveButton
          dirty={dirty}
          saving={saving}
          success={success}
          error={error}
          onSave={onSave}
          label="Save locations"
        />
      </AccordionDetails>
    </Accordion>
  );
}
