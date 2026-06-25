import { Box, Container, Grid, Typography } from '@mui/material';
import { ChangelogColumn } from './ChangelogColumn';
import { VotingColumn } from './VotingColumn';
import { GiveFeedbackBox } from './GiveFeedbackBox';
import { RESPONSIVE } from '../../config/responsive';

export function VoteFeaturesPage() {
  return (
    <Container maxWidth="lg" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Give Feedback
      </Typography>
      <GiveFeedbackBox />
      <Box sx={{ mt: RESPONSIVE.spacing.sectionMarginB }}>
        <Grid container spacing={{ xs: 2, md: 3 }}>
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
