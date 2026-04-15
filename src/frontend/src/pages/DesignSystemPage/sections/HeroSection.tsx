import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';

const HERO_COLOR_DOTS = ['#f2f1ed', '#26251e', '#f54e00', '#cf2d56', '#1f8a65'];

export function HeroSection() {
  return (
    <Box
      sx={{
        pt: { xs: 6, md: 10 },
        pb: { xs: 6, md: 8 },
        textAlign: 'center',
      }}
    >
      <Typography
        component="h1"
        sx={{
          fontSize: { xs: '2.5rem', sm: '3.38rem', md: '4rem' },
          fontWeight: 700,
          lineHeight: 1.0,
          letterSpacing: { xs: '-1.5px', md: '-2.125px' },
          color: '#26251e',
          mb: 2,
        }}
      >
        onesecondswe
      </Typography>

      <Box
        sx={{
          width: 64,
          height: 4,
          backgroundColor: '#f54e00',
          borderRadius: '2px',
          mx: 'auto',
          mb: 3,
        }}
      />

      <Typography
        sx={{
          fontSize: { xs: '1rem', md: '1.25rem' },
          fontWeight: 600,
          lineHeight: 1.4,
          letterSpacing: '-0.125px',
          color: 'rgba(38, 37, 30, 0.55)',
          maxWidth: 720,
          mx: 'auto',
          px: 2,
        }}
      >
        The onesecondswe design system. Warm visual identity with typographic clarity.
        Built on a warm off-white canvas with aggressive letter-spacing and four-weight hierarchy.
      </Typography>

      <Box
        sx={{
          display: 'flex',
          gap: 2,
          justifyContent: 'center',
          flexWrap: 'wrap',
          mt: 4,
        }}
      >
        {HERO_COLOR_DOTS.map((color) => (
          <Box
            key={color}
            sx={{
              width: 40,
              height: 40,
              borderRadius: '9999px',
              backgroundColor: color,
              border: '1px solid rgba(38, 37, 30, 0.1)',
            }}
          />
        ))}
      </Box>
    </Box>
  );
}
