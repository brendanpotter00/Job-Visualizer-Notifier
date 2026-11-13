import { useMemo } from 'react';
import { useSearchJobsBatchQuery } from '../../../features/jobs/jobsApi';
import type { LandingContent } from '../content';
import { FreshJobsTriptych } from './FreshJobsTriptych';
import { FreshJobsTriptychSkeleton } from './FreshJobsTriptychSkeleton';
import { SectionBand } from './SectionBand';
import { selectTriptychSlots, TRIPTYCH_REQUESTS } from './triptychJobs';

export function JustPostedSection({ content }: { content: LandingContent['freshJobs'] }) {
  const { data, isError } = useSearchJobsBatchQuery(TRIPTYCH_REQUESTS);
  const slots = useMemo(
    () => (data ? selectTriptychSlots(data.jobs, data.asOf) : undefined),
    [data]
  );

  if (slots) {
    if (slots.every((slot) => slot.jobs.length === 0)) return null;
    return (
      <SectionBand>
        <FreshJobsTriptych slots={slots} intro={content} cardLink={content.cardLink} />
      </SectionBand>
    );
  }
  if (isError) return null;
  return (
    <SectionBand>
      <FreshJobsTriptychSkeleton content={content} />
    </SectionBand>
  );
}
