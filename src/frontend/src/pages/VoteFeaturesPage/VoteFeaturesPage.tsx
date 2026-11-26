import { Box, Container, Typography } from '@mui/material';
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
        <VotingColumn />
      </Box>
    </Container>
  );
}
