import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

export interface SelectedCompany {
  id: string;
  name: string;
}

export interface SelectedCompaniesPanelProps {
  selectedCompanies: SelectedCompany[];
  onRemove: (id: string) => void;
}

// Ordering is the caller's responsibility; this renders in the given order.
export function SelectedCompaniesPanel({
  selectedCompanies,
  onRemove,
}: SelectedCompaniesPanelProps) {
  const selectedCount = selectedCompanies.length;

  return (
    <Accordion
      defaultExpanded
      disableGutters
      elevation={0}
      slotProps={{ transition: { unmountOnExit: true } }}
      sx={{
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        mb: 3,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" alignItems="center" spacing={1}>
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
      </AccordionSummary>
      <AccordionDetails>
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
      </AccordionDetails>
    </Accordion>
  );
}
