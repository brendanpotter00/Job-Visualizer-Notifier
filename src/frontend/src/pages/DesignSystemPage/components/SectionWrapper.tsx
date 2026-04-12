import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import type { ReactNode } from 'react';

interface SectionWrapperProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export function SectionWrapper({ title, subtitle, children }: SectionWrapperProps) {
  return (
    <Box sx={{ mb: 8 }}>
      <Typography
        component="h2"
        sx={{
          fontSize: '3rem',
          fontWeight: 700,
          lineHeight: 1.0,
          letterSpacing: '-1.5px',
          color: '#26251e',
          mb: subtitle ? 1 : 4,
        }}
      >
        {title}
      </Typography>
      {subtitle && (
        <Typography
          sx={{
            fontSize: '1.25rem',
            fontWeight: 600,
            lineHeight: 1.4,
            letterSpacing: '-0.125px',
            color: 'rgba(38, 37, 30, 0.55)',
            mb: 4,
          }}
        >
          {subtitle}
        </Typography>
      )}
      {children}
    </Box>
  );
}
