import type { ReactNode } from 'react';
import { Box } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';

export function SectionBand({ children }: { children: ReactNode }) {
  return <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>{children}</Box>;
}
