import { Box, Container, Typography } from '@mui/material';
import { COMPANIES } from '../../config/companies.ts';
import { useEffect } from 'react';
import { loadJobsForCompany } from '../../features/jobs/jobsThunks.ts';
import { useAppDispatch, useAppSelector } from '../../app/hooks.ts';

/**
 * Recent Job Postings page component
 *
 * Placeholder page for future feature showing recently posted jobs
 * across all companies.
 *
 * @returns Recent job postings page with placeholder content
 */
export function RecentJobPostingsPage() {
  const dispatch = useAppDispatch();
  const allJobs = useAppSelector((state) => state.jobs);

  useEffect(() => {
    COMPANIES.forEach((company) => {
      dispatch(loadJobsForCompany({ companyId: company.id }));
    });
  }, [dispatch]);

  console.log(allJobs);

  return (
    <Container maxWidth="xl">
      <Box sx={{ my: 4 }}>
        <Typography variant="h3" component="h1" gutterBottom>
          Recent Job Postings
        </Typography>
        <Typography variant="body1" color="text.secondary">
          This page is under construction. Check back soon!
        </Typography>
      </Box>
    </Container>
  );
}
