import { Box, Container, Grid, Typography } from '@mui/material';
import { ChangelogColumn } from './ChangelogColumn';
import { VotingColumn } from './VotingColumn';
import { GiveFeedbackBox } from './GiveFeedbackBox';

export function VoteFeaturesPage() {
  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Give Feedback
      </Typography>
      <GiveFeedbackBox />
      <Box sx={{ mt: 3 }}>
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 6 }} sx={{ order: { xs: 2, md: 1 } }}>
            <ChangelogColumn />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }} sx={{ order: { xs: 1, md: 2 } }}>
            <VotingColumn />
          </Grid>
        </Grid>
      </Box>
    </Container>
  );
}
