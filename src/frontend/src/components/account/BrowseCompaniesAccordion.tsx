import type { ReactNode } from 'react';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Typography from '@mui/material/Typography';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

export interface BrowseCompaniesAccordionProps {
  selectedCount: number;
  totalCount: number;
  children: ReactNode;
}

/**
 * Collapsed-by-default accordion that reveals the full company chip grid
 * inside. Summary label shows "Browse and select all companies" with a
 * "{selected} of {total} selected" subtitle.
 */
export function BrowseCompaniesAccordion({
  selectedCount,
  totalCount,
  children,
}: BrowseCompaniesAccordionProps) {
  return (
    <Accordion
      disableGutters
      elevation={0}
      slotProps={{ transition: { unmountOnExit: true } }}
      sx={{
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          Browse and select all companies
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
          {selectedCount} of {totalCount} selected
        </Typography>
      </AccordionSummary>
      <AccordionDetails>{children}</AccordionDetails>
    </Accordion>
  );
}
