import { Box, Container, Grid, Typography } from '@mui/material';
import { ChangelogColumn } from './ChangelogColumn';
import { VotingColumn } from './VotingColumn';

export function VoteFeaturesPage() {
  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Vote for features
      </Typography>
      <Box sx={{ mt: 3 }}>
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 6 }}>
            <ChangelogColumn />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <VotingColumn />
          </Grid>
        </Grid>
      </Box>
    </Container>
  );
}
