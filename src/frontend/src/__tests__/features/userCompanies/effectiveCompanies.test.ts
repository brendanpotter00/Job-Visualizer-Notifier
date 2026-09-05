import { describe, it, expect, afterEach, vi } from 'vitest';

/**
 * The effective-company seam: the curated roster PLUS the signed-in viewer's own
 * boards, as the narrow `CompanyOption` type the `/companies` page selects from.
 *
 * The identity assertions here are the ones that matter. `selectEffectiveCompanies`
 * must return `PUBLIC_COMPANY_OPTIONS` **by reference** (`toBe`, never `toEqual`)
 * whenever the flag is off, the viewer is signed out, or they own nothing — that
 * is what makes this a provable no-op for every downstream memo, and therefore
 * what makes the flag-off build indistinguishable from one without the feature.
 */
const { flagState } = vi.hoisted(() => ({ flagState: { isEnabled: true } }));
vi.mock('../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: {
    get isEnabled() {
      return flagState.isEnabled;
    },
    isDiscoveryProgressEnabled: false,
  },
}));

import { createTestStore } from '../../../test/testUtils';
import type { RootState } from '../../../app/store';
import { userCompaniesApi } from '../../../features/userCompanies/userCompaniesApi';
import type { UserCompany } from '../../../features/userCompanies/userCompaniesApi';
import {
  EMPTY_ID_SET,
  PUBLIC_COMPANY_OPTIONS,
  selectEffectiveCompanies,
  selectEffectiveCompanyById,
  selectUserCompanyIdSet,
} from '../../../features/userCompanies/effectiveCompanies';

function userCompany(overrides: Partial<UserCompany> & Pick<UserCompany, 'id'>): UserCompany {
  return {
    displayName: 'Acme',
    ats: 'greenhouse',
    boardToken: 'acme',
    sourceId: `custom:${overrides.id}`,
    healthState: 'healthy',
    openJobCount: 10,
    lastSuccessAt: '2026-08-30T00:00:00.000Z',
    trackingStartedAt: '2026-08-01T00:00:00.000Z',
    ...overrides,
  };
}

async function storeWithBoards(companies: UserCompany[]) {
  const store = createTestStore();
  await store.dispatch(
    userCompaniesApi.util.upsertQueryData('getUserCompanies', undefined, { companies })
  );
  return store;
}

const state = (store: { getState: () => unknown }) => store.getState() as RootState;

afterEach(() => {
  flagState.isEnabled = true;
});

describe('T1 — identity when there is nothing to add', () => {
  it('returns the module constants BY REFERENCE with no cached user companies', () => {
    const store = createTestStore();
    expect(selectEffectiveCompanies(state(store))).toBe(PUBLIC_COMPANY_OPTIONS);
    expect(selectUserCompanyIdSet(state(store))).toBe(EMPTY_ID_SET);
  });

  it('returns them BY REFERENCE for a signed-in owner of zero boards', async () => {
    const store = await storeWithBoards([]);
    expect(selectEffectiveCompanies(state(store))).toBe(PUBLIC_COMPANY_OPTIONS);
    expect(selectUserCompanyIdSet(state(store))).toBe(EMPTY_ID_SET);
  });

  it('returns them BY REFERENCE with the flag off, even with boards in the cache', async () => {
    const store = await storeWithBoards([userCompany({ id: 'u-abc123' })]);
    flagState.isEnabled = false;
    expect(selectEffectiveCompanies(state(store))).toBe(PUBLIC_COMPANY_OPTIONS);
    expect(selectUserCompanyIdSet(state(store))).toBe(EMPTY_ID_SET);
    expect(selectEffectiveCompanyById(state(store), 'u-abc123')).toBeUndefined();
  });

  it('every public option is non-custom and carries a source label', () => {
    expect(PUBLIC_COMPANY_OPTIONS.length).toBeGreaterThan(50);
    expect(PUBLIC_COMPANY_OPTIONS.every((o) => o.isCustom === false)).toBe(true);
    expect(PUBLIC_COMPANY_OPTIONS.every((o) => o.sourceLabel.length > 0)).toBe(true);
    // Sorted by name, which is what the dropdown relies on.
    const names = PUBLIC_COMPANY_OPTIONS.map((o) => o.name);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
  });
});

describe('the viewer owns boards', () => {
  it('INTERLEAVES them into one alphabetical list, not a block at the end', async () => {
    // They used to be appended after all ~135 curated companies, under a "Your
    // companies" heading. Finding a board you track meant first knowing which of
    // the two lists it was filed under — so a company now sits where its name
    // says it does, and the badge carries the distinction instead.
    const store = await storeWithBoards([
      userCompany({ id: 'u-zzz', displayName: 'Zebra Corp' }),
      userCompany({ id: 'u-aaa', displayName: 'Aardvark Inc' }),
    ]);
    const options = selectEffectiveCompanies(state(store));

    expect(options).not.toBe(PUBLIC_COMPANY_OPTIONS);
    expect(options.length).toBe(PUBLIC_COMPANY_OPTIONS.length + 2);

    const names = options.map((o) => o.name);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));

    // "Aardvark Inc" sorts to the very front, ahead of every curated company —
    // which is precisely what appending could never do.
    expect(names[0]).toBe('Aardvark Inc');
    expect(options[0].isCustom).toBe(true);

    // Every curated company is still present and still not custom.
    const curated = options.filter((o) => !o.isCustom);
    expect(curated).toEqual([...PUBLIC_COMPANY_OPTIONS]);

    expect(options.filter((o) => o.isCustom).map((o) => o.name)).toEqual([
      'Aardvark Inc',
      'Zebra Corp',
    ]);
    expect(selectUserCompanyIdSet(state(store))).toEqual(new Set(['u-zzz', 'u-aaa']));
  });

  it('THE RENAME WINS — the wire `displayName` is already the effective name', async () => {
    // Production shape: the board was discovered as "cisco" and the owner
    // renamed it. The server sends COALESCE(user_display_name, display_name),
    // so there is nothing to merge here — but a lookup that fell back to the
    // static roster, or to the board token, would show the old name.
    const store = await storeWithBoards([
      userCompany({
        id: 'u-jw8iz8sqvy',
        displayName: 'Raindrop YC',
        ats: 'discovered',
        boardToken: 'https://raindrop.example.com/careers',
      }),
    ]);
    const option = selectEffectiveCompanyById(state(store), 'u-jw8iz8sqvy');
    expect(option?.name).toBe('Raindrop YC');
    expect(option?.isCustom).toBe(true);
  });

  it('uses the board host as the source label and the board URL as the jobs link', async () => {
    const store = await storeWithBoards([
      userCompany({
        id: 'u-disc',
        displayName: 'Jane Street',
        ats: 'discovered',
        boardToken: 'https://www.janestreet.com/join-jane-street/open-roles/',
      }),
      userCompany({ id: 'u-gh', displayName: 'Zeta', ats: 'greenhouse', boardToken: 'zeta' }),
    ]);
    const discovered = selectEffectiveCompanyById(state(store), 'u-disc');
    expect(discovered?.sourceLabel).toBe('janestreet.com');
    expect(discovered?.jobsUrl).toBe('https://www.janestreet.com/join-jane-street/open-roles/');

    const greenhouse = selectEffectiveCompanyById(state(store), 'u-gh');
    expect(greenhouse?.sourceLabel).toBe('job-boards.greenhouse.io');
    expect(greenhouse?.jobsUrl).toBe('https://job-boards.greenhouse.io/zeta');
  });

  it('falls back to a generic label — never a guessed link — when no board URL is derivable', async () => {
    // Workday's board token is a cosmetic tenant label; the real host is not on
    // the wire, so a link would be a confident 404.
    const store = await storeWithBoards([
      userCompany({ id: 'u-wd', displayName: 'Tenant Co', ats: 'workday', boardToken: 'tenant' }),
    ]);
    const option = selectEffectiveCompanyById(state(store), 'u-wd');
    expect(option?.jobsUrl).toBeUndefined();
    expect(option?.sourceLabel).toBe('Custom Board');
  });

  it('never carries a recruiter link for a board the user brought themselves', async () => {
    const store = await storeWithBoards([userCompany({ id: 'u-abc123' })]);
    expect(selectEffectiveCompanyById(state(store), 'u-abc123')?.recruiterLinkedInUrl).toBe(
      undefined
    );
  });

  it('still resolves curated companies, and still answers undefined for an unknown id', async () => {
    const store = await storeWithBoards([userCompany({ id: 'u-abc123' })]);
    expect(selectEffectiveCompanyById(state(store), 'spacex')?.isCustom).toBe(false);
    expect(selectEffectiveCompanyById(state(store), 'does-not-exist')).toBeUndefined();
    expect(selectEffectiveCompanyById(state(store), 'u-not-mine')).toBeUndefined();
  });

  it('keeps its result stable across reads, so component lookups do not re-render', async () => {
    const store = await storeWithBoards([userCompany({ id: 'u-abc123' })]);
    expect(selectEffectiveCompanies(state(store))).toBe(selectEffectiveCompanies(state(store)));
    expect(selectEffectiveCompanyById(state(store), 'u-abc123')).toBe(
      selectEffectiveCompanyById(state(store), 'u-abc123')
    );
  });
});
