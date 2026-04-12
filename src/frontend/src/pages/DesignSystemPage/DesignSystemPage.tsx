import { useEffect } from 'react';
import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import { DS_FONT_FAMILY } from './designTokens';
import { HeroSection } from './sections/HeroSection';
import { ColorPaletteSection } from './sections/ColorPaletteSection';
import { TypographySection } from './sections/TypographySection';
import { ComponentsSection } from './sections/ComponentsSection';
import { SpacingSection } from './sections/SpacingSection';
import { ElevationSection } from './sections/ElevationSection';
import { BorderRadiusSection } from './sections/BorderRadiusSection';

const GOOGLE_FONTS_URL =
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';

export function DesignSystemPage() {
  // Load Inter font dynamically (dev-only page, no index.html changes)
  useEffect(() => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = GOOGLE_FONTS_URL;
    document.head.appendChild(link);
    return () => {
      document.head.removeChild(link);
    };
  }, []);

  return (
    <Box
      sx={{
        backgroundColor: '#f2f1ed',
        color: '#26251e',
        fontFamily: DS_FONT_FAMILY.primary,
        minHeight: '100vh',
        // Negative margins to break out of RootLayout padding and fill full width
        mx: { xs: -2, sm: -3, md: -4 },
        mt: -1,
      }}
    >
      <Container maxWidth="lg" sx={{ px: { xs: 2, sm: 3, md: 4 } }}>
        <HeroSection />
        <ColorPaletteSection />
        <TypographySection />
        <ComponentsSection />
        <SpacingSection />
        <ElevationSection />
        <BorderRadiusSection />

        {/* Footer spacer */}
        <Box sx={{ pb: 8 }} />
      </Container>
    </Box>
  );
}
