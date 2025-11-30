import { Box, Link, Typography } from '@mui/material';

/**
 * Application footer component
 *
 * Displays attribution with LinkedIn profile link
 *
 * @returns The application footer
 */
export function AppFooter() {
  return (
    <Box
      component="footer"
      sx={{
        mt: 6,
        mb: 2,
        pt: 3,
        borderTop: '1px solid',
        borderColor: 'divider',
        textAlign: 'center',
      }}
    >
      <Typography variant="body2" color="text.secondary">
        Made by{' '}
        <Link
          href="https://www.linkedin.com/in/brendan-potter00/"
          target="_blank"
          rel="noopener noreferrer"
          sx={{
            color: 'primary.main',
            textDecoration: 'none',
            '&:hover': {
              textDecoration: 'underline',
            },
          }}
        >
          Brendan Potter
        </Link>
      </Typography>
    </Box>
  );
}
