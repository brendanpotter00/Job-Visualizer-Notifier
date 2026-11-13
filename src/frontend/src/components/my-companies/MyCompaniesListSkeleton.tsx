import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { CardListSkeleton } from '../shared/Skeletons';

const ROW_COUNT = 3;

export function MyCompaniesListSkeleton() {
  return (
    <Box data-testid="my-companies-list-skeleton">
      <Typography variant="h6" component="div" gutterBottom>
        Your companies
      </Typography>
      <CardListSkeleton count={ROW_COUNT} lines={2} trailing spacing={1.5} />
    </Box>
  );
}
