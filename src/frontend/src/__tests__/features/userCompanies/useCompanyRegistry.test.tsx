import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import type { Company } from '../../../types';
import { COMPANIES } from '../../../config/companies';
import type { CompanyDTO } from '../../../features/userCompanies/userCompaniesApi';
import {
  companyFromDto,
  mergeCompanies,
  useCompanyRegistry,
  useGetCompanyById,
} from '../../../features/userCompanies/useCompanyRegistry';

// Mock the auth hook and the RTK Query hook the registry depends on so we can
// drive anonymous vs authenticated + runtime-company states without a store.
const mockAuth = { isAuthenticated: false };
vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuth,
}));

const mockUserCompaniesQuery: {
  data: CompanyDTO[] | undefined;
  isLoading: boolean;
  isUninitialized: boolean;
  isError: boolean;
} = { data: undefined, isLoading: false, isUninitialized: true, isError: false };

vi.mock('../../../features/userCompanies/userCompaniesApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../features/userCompanies/userCompaniesApi')>();
  return {
    ...actual,
    useGetUserCompaniesQuery: () => mockUserCompaniesQuery,
  };
});

const dto = (overrides: Partial<CompanyDTO> = {}): CompanyDTO => ({
  id: 'acme',
  name: 'Acme',
  jobsUrl: 'https://jobs.example.com/acme',
  sourceAts: 'custom_json',
  ...overrides,
});

function setAuthenticated(companies: CompanyDTO[] | undefined) {
  mockAuth.isAuthenticated = true;
  mockUserCompaniesQuery.data = companies;
  mockUserCompaniesQuery.isUninitialized = false;
  mockUserCompaniesQuery.isLoading = false;
  mockUserCompaniesQuery.isError = false;
}

describe('companyFromDto', () => {
  it('maps a DTO to a backend-scraper Company', () => {
    const company = companyFromDto(dto());
    expect(company).toMatchObject({
      id: 'acme',
      name: 'Acme',
      ats: 'backend-scraper',
      jobsUrl: 'https://jobs.example.com/acme',
      sourceAts: 'custom_json',
      config: { type: 'backend-scraper', companyId: 'acme', apiBaseUrl: '/api/jobs' },
    });
  });

  it('maps a null jobsUrl to undefined', () => {
    expect(companyFromDto(dto({ jobsUrl: null })).jobsUrl).toBeUndefined();
  });
});

describe('mergeCompanies', () => {
  const s = (id: string, name: string): Company => ({
    id,
    name,
    ats: 'backend-scraper',
    config: { type: 'backend-scraper', companyId: id, apiBaseUrl: '/api/jobs' },
  });

  it('appends runtime companies not present in the static list', () => {
    const merged = mergeCompanies([s('a', 'A')], [s('b', 'B')]);
    expect(merged.map((c) => c.id)).toEqual(['a', 'b']);
  });

  it('dedupes by id with the static entry winning on collision', () => {
    const merged = mergeCompanies([s('a', 'Static A')], [s('a', 'Runtime A'), s('b', 'B')]);
    expect(merged.map((c) => c.id)).toEqual(['a', 'b']);
    expect(merged.find((c) => c.id === 'a')?.name).toBe('Static A');
  });

  it('returns the same static array reference when runtime is empty', () => {
    const staticList = [s('a', 'A')];
    expect(mergeCompanies(staticList, [])).toBe(staticList);
  });
});

describe('useCompanyRegistry', () => {
  beforeEach(() => {
    mockAuth.isAuthenticated = false;
    mockUserCompaniesQuery.data = undefined;
    mockUserCompaniesQuery.isLoading = false;
    mockUserCompaniesQuery.isUninitialized = true;
    mockUserCompaniesQuery.isError = false;
  });

  it('is exactly the static list for anonymous users', () => {
    const { result } = renderHook(() => useCompanyRegistry());
    expect(result.current).toBe(COMPANIES);
  });

  it('merges runtime companies for authenticated users', () => {
    setAuthenticated([dto({ id: 'runtime-co', name: 'Runtime Co' })]);
    const { result } = renderHook(() => useCompanyRegistry());
    expect(result.current.length).toBe(COMPANIES.length + 1);
    const added = result.current.find((c) => c.id === 'runtime-co');
    expect(added?.name).toBe('Runtime Co');
    expect(added?.ats).toBe('backend-scraper');
  });

  it('does not duplicate a runtime company that collides with a static id', () => {
    const staticId = COMPANIES[0].id;
    setAuthenticated([dto({ id: staticId, name: 'Impostor' })]);
    const { result } = renderHook(() => useCompanyRegistry());
    expect(result.current.length).toBe(COMPANIES.length);
    expect(result.current.find((c) => c.id === staticId)?.name).toBe(COMPANIES[0].name);
  });

  it('resolves runtime companies through useGetCompanyById', () => {
    setAuthenticated([dto({ id: 'runtime-co', name: 'Runtime Co' })]);
    const { result } = renderHook(() => useGetCompanyById());
    expect(result.current('runtime-co')?.name).toBe('Runtime Co');
    expect(result.current('does-not-exist')).toBeUndefined();
  });
});
