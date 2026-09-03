import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../app/store';
import { COMPANIES } from '../../config/companies';
import { getCompanySourceLabel } from '../../config/atsSource';
import { CUSTOM_COMPANIES_CONFIG } from '../../config/customCompanies';
import { sourceBoardLabel, sourceBoardUrl } from '../../components/my-companies/companyHealth';
import { userCompaniesApi } from './userCompaniesApi';
import type { UserCompany } from './userCompaniesApi';

/**
 * One entry in the Company Hiring Trends dropdown: a curated compile-time
 * company, or one of the signed-in caller's own private boards.
 *
 * DELIBERATELY NARROWER THAN `Company`. A `Company` carries `ats` + `config`,
 * and `getClientForATS` (`api/utils.ts`) dispatches on `ats` — so minting a
 * synthetic `Company` for a `u-<id>` board would hand that id to the PUBLIC
 * `/api/jobs` client, which is exactly the request that must never be made
 * (`/api/jobs` excludes `visibility='user'` rows unconditionally, so it would
 * also silently return nothing). This type cannot be passed to that dispatcher
 * at all: it has no `ats` and no `config`. The only thing that decides how a
 * board's jobs are fetched is `isCustomCompanyId`, inside `getJobsForCompany`.
 */
export interface CompanyOption {
  /** `COMPANY_IDS` member for a curated company, `u-<base36>` for a custom board. */
  id: string;
  /**
   * What to call it. For a custom board this is `UserCompany.displayName`, which
   * the backend already resolves as `COALESCE(user_display_name, display_name)`
   * — so a rename the user made wins here for free, with nothing to merge.
   */
  name: string;
  isCustom: boolean;
  /** The company's own postings page, or the board a custom row was built from. */
  jobsUrl?: string;
  /** Public-company nicety; never set for a custom board. */
  recruiterLinkedInUrl?: string;
  /** "Greenhouse" / "Custom Web Scraper" for a curated company; the board host for a custom one. */
  sourceLabel: string;
}

/**
 * What a custom board's source line says when its board URL is not derivable
 * (`sourceBoardUrl` returns null for Workday/Eightfold slugs and for anything
 * that does not parse as `http(s)`). A generic word rather than a guessed host:
 * the label must never disagree with a link that isn't there.
 */
const CUSTOM_BOARD_SOURCE_LABEL = 'Custom Board';

/**
 * The curated roster as dropdown options, sorted by name, built ONCE.
 *
 * Identity matters: `selectEffectiveCompanies` returns this exact array by
 * reference whenever the flag is off, the caller is signed out, or they own no
 * boards. That is what makes the flag-off path a provable no-op for every
 * downstream memo — and it is asserted with `toBe`, not `toEqual`.
 */
export const PUBLIC_COMPANY_OPTIONS: readonly CompanyOption[] = Object.freeze(
  [...COMPANIES]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((company) =>
      Object.freeze({
        id: company.id,
        name: company.name,
        isCustom: false,
        jobsUrl: company.jobsUrl,
        recruiterLinkedInUrl: company.recruiterLinkedInUrl,
        sourceLabel: getCompanySourceLabel(company),
      })
    )
);

/** The "no custom boards" id set, by reference. Same identity guarantee as above. */
export const EMPTY_ID_SET: ReadonlySet<string> = new Set<string>();

function toCustomOption(company: UserCompany): CompanyOption {
  const boardUrl = sourceBoardUrl(company);
  return {
    id: company.id,
    name: company.displayName,
    isCustom: true,
    jobsUrl: boardUrl ?? undefined,
    // Left undefined on purpose — there is no curated recruiter link for a board
    // the user brought themselves, and inventing one would be a dead link.
    recruiterLinkedInUrl: undefined,
    sourceLabel: (boardUrl ? sourceBoardLabel(boardUrl) : null) ?? CUSTOM_BOARD_SOURCE_LABEL,
  };
}

/**
 * The caller's own boards, straight out of the RTK Query cache
 * (`GET /api/users/companies`) — NO new endpoint and NO new request. The pages
 * that need this already subscribe to that query; this selector only reads
 * whatever the subscription has put in the store.
 *
 * `undefined` while the flag is off, signed out (the query is skipped, so it
 * never resolves), or before the first response lands. All three mean the same
 * thing to every consumer: there are no custom boards.
 */
function selectOwnedUserCompanies(state: RootState): readonly UserCompany[] | undefined {
  if (!CUSTOM_COMPANIES_CONFIG.isEnabled) return undefined;
  return userCompaniesApi.endpoints.getUserCompanies.select()(state).data?.companies;
}

/**
 * Ids of the caller's own boards — the set `lib/url.ts` validates `?company=`
 * against, so a `u-<id>` deep link resolves for its owner and for nobody else.
 */
export const selectUserCompanyIdSet = createSelector(
  [selectOwnedUserCompanies],
  (companies): ReadonlySet<string> =>
    companies && companies.length > 0 ? new Set(companies.map((c) => c.id)) : EMPTY_ID_SET
);

/**
 * Every company the current viewer can select on `/companies`: the curated
 * roster, then their own boards (each group already sorted by name).
 *
 * Returns `PUBLIC_COMPANY_OPTIONS` BY REFERENCE when there is nothing to add.
 */
export const selectEffectiveCompanies = createSelector(
  [selectOwnedUserCompanies],
  (companies): readonly CompanyOption[] => {
    if (!companies || companies.length === 0) return PUBLIC_COMPANY_OPTIONS;
    // ONE ALPHABETICAL LIST, custom boards interleaved rather than appended.
    // They used to be a second block under a "Your companies" heading, which
    // meant that finding a company you track required knowing which of the two
    // lists it was in first — and the person looking for "Cisco" is looking for
    // Cisco, not for the category we happen to file it under. The `isCustom`
    // flag survives on each option and the dropdown marks those rows with a
    // badge, so the distinction is still visible where it is cheap to read.
    return [...PUBLIC_COMPANY_OPTIONS, ...companies.map(toCustomOption)].sort((a, b) =>
      a.name.localeCompare(b.name)
    );
  }
);

/**
 * One company by id, curated or custom. `undefined` for an id neither knows —
 * a company dropped from `companies.ts`, or somebody else's board id pasted
 * into the URL — and every caller renders its own fallback for that.
 *
 * Not a `createSelector`: the result is an element of the memoized array above,
 * so it is already referentially stable across renders, and a parameterized
 * memo would need a cache keyed by id to be any better than this `find` over
 * ~40 entries.
 */
export function selectEffectiveCompanyById(
  state: RootState,
  id: string
): CompanyOption | undefined {
  return selectEffectiveCompanies(state).find((option) => option.id === id);
}
