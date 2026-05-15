import type { AshbyJobResponse } from '../types';

const CURSOR_BOARD_URL_PREFIX = 'https://jobs.ashbyhq.com/cursor/';

function slugify(input: string): string {
  return input
    .toLowerCase()
    .replace(/[/&]/g, ' ')
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
}

/**
 * Cursor uses Ashby as their ATS but renders postings on cursor.com/careers.
 * Their slug convention:
 *   - unique title        → slugify(title)
 *   - duplicated title    → slugify(title) + '-' + slugify(location)
 *
 * When the batch comes from Cursor's Ashby board, rewrite every jobUrl to its
 * cursor.com/careers equivalent so clicking a row opens Cursor's branded page.
 */
export function rewriteCursorJobUrls(
  jobs: AshbyJobResponse[]
): AshbyJobResponse[] {
  if (jobs.length === 0) return jobs;
  const isCursor = jobs.some((j) =>
    j.jobUrl?.startsWith(CURSOR_BOARD_URL_PREFIX)
  );
  if (!isCursor) return jobs;

  const titleCounts = new Map<string, number>();
  for (const j of jobs) {
    titleCounts.set(j.title, (titleCounts.get(j.title) ?? 0) + 1);
  }

  return jobs.map((job) => {
    const titleSlug = slugify(job.title);
    const slug =
      (titleCounts.get(job.title) ?? 0) > 1
        ? `${titleSlug}-${slugify(job.location)}`
        : titleSlug;
    return { ...job, jobUrl: `https://cursor.com/careers/${slug}` };
  });
}
