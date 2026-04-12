import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { SectionWrapper } from '../components/SectionWrapper';
import { DS_ELEVATION } from '../designTokens';

export function ElevationSection() {
  return (
    <SectionWrapper title="Depth & Elevation" subtitle="Borders use oklab color space for perceptual uniformity. Shadows use large blur values for atmospheric lift.">
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: '1fr',
            sm: 'repeat(2, 1fr)',
            md: 'repeat(3, 1fr)',
          },
          gap: 3,
        }}
      >
        {DS_ELEVATION.map((level) => (
          <Box
            key={level.level}
            sx={{
              backgroundColor: '#f2f1ed',
              borderRadius: '8px',
              p: 3,
              boxShadow: level.boxShadow,
              minHeight: 120,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}
          >
            <Box>
              <Typography
                sx={{
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  letterSpacing: '0.125px',
                  color: 'rgba(38, 37, 30, 0.55)',
                  textTransform: 'uppercase',
                  mb: 0.5,
                }}
              >
                Level {level.level}
              </Typography>
              <Typography
                sx={{
                  fontSize: '1.25rem',
                  fontWeight: 700,
                  letterSpacing: '-0.125px',
                  color: '#26251e',
                }}
              >
                {level.name}
              </Typography>
            </Box>
            <Typography
              sx={{
                fontSize: '0.875rem',
                color: 'rgba(38, 37, 30, 0.55)',
                mt: 1,
              }}
            >
              {level.description}
            </Typography>
          </Box>
        ))}
      </Box>
    </SectionWrapper>
  );
}
