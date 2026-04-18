import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

export interface SelectedCompany {
  id: string;
  name: string;
}

export interface SelectedCompaniesPanelProps {
  selectedCompanies: SelectedCompany[];
  onRemove: (id: string) => void;
}

/**
 * Displays the current draft of selected companies as chips with delete
 * affordances. Shows an empty-state dashed box when nothing is selected.
 * Ordering is the caller's responsibility (we render in the given order).
 */
export function SelectedCompaniesPanel({
  selectedCompanies,
  onRemove,
}: SelectedCompaniesPanelProps) {
  const selectedCount = selectedCompanies.length;

  return (
    <Box sx={{ mb: 3 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          Your selected companies
        </Typography>
        <Chip
          label={selectedCount}
          size="small"
          data-testid="selected-count"
          sx={{ height: 20, fontSize: '0.7rem', fontWeight: 700, px: 0.5 }}
        />
      </Stack>

      {selectedCount === 0 ? (
        <Box
          sx={{
            p: 2.5,
            border: '1px dashed',
            borderColor: 'divider',
            borderRadius: 1,
            textAlign: 'center',
          }}
        >
          <Typography variant="body2" color="text.secondary">
            No companies selected. You'll see postings from all companies.
          </Typography>
        </Box>
      ) : (
        <Box
          sx={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 1,
            p: 1.5,
            bgcolor: 'action.hover',
            borderRadius: 1,
          }}
        >
          {selectedCompanies.map((c) => (
            <Chip
              key={c.id}
              label={c.name}
              onDelete={() => onRemove(c.id)}
              color="primary"
              variant="filled"
              size="small"
              data-testid={`selected-chip-${c.name}`}
            />
          ))}
        </Box>
      )}
    </Box>
  );
}
