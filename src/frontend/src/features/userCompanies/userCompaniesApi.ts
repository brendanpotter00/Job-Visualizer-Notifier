import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

/**
 * Wire-format DTO for a runtime user-added company, as returned by the backend
 * `/api/users/companies` endpoints (camelCase JSON). Distinct from the frontend
 * `Company` model — map a DTO to a `Company` via `companyFromDto`
 * (see `useCompanyRegistry.ts`).
 */
export interface CompanyDTO {
  id: string;
  name: string;
  jobsUrl: string | null;
  /**
   * Backend provider slug. One of the migrated ATSes
   * (greenhouse|ashby|lever|gem|eightfold|workday) or `'custom_json'` when the
   * careers page had no recognized ATS and the backend built a custom recipe.
   */
  sourceAts: string;
}

/** Terminal-or-pending result of `POST /api/users/companies`. */
export type AddCompanyResult =
  | { status: 'added' | 'alreadyTracked'; company: CompanyDTO }
  | { status: 'pending'; submissionId: string };

/** Result of polling `GET /api/users/companies/submissions/{id}`. */
export interface SubmissionResult {
  id: string;
  status: 'pending' | 'succeeded' | 'failed';
  company: CompanyDTO | null;
  error: string | null;
}

/**
 * The RTK Query `extra` argument shape this slice reads. Mirrors
 * `savedFiltersApi` exactly — the store wires `{ getTokenOrNull }` as the thunk
 * `extraArgument` (see `app/store.ts`), and `prepareHeaders` reads it to attach
 * the Bearer token. Do NOT invent a new token mechanism.
 */
interface UserCompaniesApiExtra {
  getTokenOrNull: () => Promise<string | null>;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return v != null && typeof v === 'object' && !Array.isArray(v);
}

/**
 * Validate an untrusted value as a `CompanyDTO`. A 2xx body with the wrong
 * shape (CDN error page, serializer regression) must surface as an error rather
 * than silently feeding a malformed company into the registry.
 */
function validateCompanyDto(value: unknown, ctx: string): CompanyDTO {
  if (!isRecord(value)) {
    throw new Error(`Invalid ${ctx}: company is not an object`);
  }
  if (typeof value.id !== 'string') {
    throw new Error(`Invalid ${ctx}: company.id must be a string`);
  }
  if (typeof value.name !== 'string') {
    throw new Error(`Invalid ${ctx}: company.name must be a string`);
  }
  if (value.jobsUrl !== null && typeof value.jobsUrl !== 'string') {
    throw new Error(`Invalid ${ctx}: company.jobsUrl must be a string or null`);
  }
  if (typeof value.sourceAts !== 'string') {
    throw new Error(`Invalid ${ctx}: company.sourceAts must be a string`);
  }
  return {
    id: value.id,
    name: value.name,
    jobsUrl: value.jobsUrl,
    sourceAts: value.sourceAts,
  };
}

function validateAddCompanyResult(res: unknown): AddCompanyResult {
  const ctx = 'POST /api/users/companies response';
  if (!isRecord(res)) {
    throw new Error(`Invalid ${ctx}: body is not an object`);
  }
  if (res.status === 'added' || res.status === 'alreadyTracked') {
    return { status: res.status, company: validateCompanyDto(res.company, ctx) };
  }
  if (res.status === 'pending') {
    if (typeof res.submissionId !== 'string') {
      throw new Error(`Invalid ${ctx}: submissionId must be a string`);
    }
    return { status: 'pending', submissionId: res.submissionId };
  }
  throw new Error(`Invalid ${ctx}: unexpected status`);
}

function validateSubmissionResult(res: unknown): SubmissionResult {
  const ctx = 'GET /api/users/companies/submissions/{id} response';
  if (!isRecord(res)) {
    throw new Error(`Invalid ${ctx}: body is not an object`);
  }
  if (typeof res.id !== 'string') {
    throw new Error(`Invalid ${ctx}: id must be a string`);
  }
  if (res.status !== 'pending' && res.status !== 'succeeded' && res.status !== 'failed') {
    throw new Error(`Invalid ${ctx}: unexpected status`);
  }
  const company = res.company == null ? null : validateCompanyDto(res.company, ctx);
  const error = res.error == null ? null : String(res.error);
  return { id: res.id, status: res.status, company, error };
}

export const userCompaniesApi = createApi({
  reducerPath: 'userCompaniesApi',
  baseQuery: fetchBaseQuery({
    baseUrl: '/api/users',
    prepareHeaders: async (headers, { extra }) => {
      const { getTokenOrNull } = extra as UserCompaniesApiExtra;
      const token = await getTokenOrNull();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      return headers;
    },
  }),
  tagTypes: ['UserCompanies'],
  endpoints: (builder) => ({
    // The caller's runtime-added (custom, unlisted) tracked companies. Curated
    // companies are already in the static `COMPANIES` list, so they are NOT
    // returned here. Anonymous callers get `{ companies: [] }`.
    getUserCompanies: builder.query<CompanyDTO[], void>({
      query: () => '/companies',
      transformResponse: (res: unknown): CompanyDTO[] => {
        if (!isRecord(res) || !Array.isArray(res.companies)) {
          throw new Error('Invalid GET /api/users/companies response: missing companies[]');
        }
        return res.companies.map((c) => validateCompanyDto(c, 'GET /api/users/companies response'));
      },
      providesTags: ['UserCompanies'],
      // Keep the registry warm across navigations (mirrors savedFiltersApi).
      keepUnusedDataFor: 300,
    }),
    addCompany: builder.mutation<AddCompanyResult, { url: string }>({
      query: (body) => ({ url: '/companies', method: 'POST', body }),
      transformResponse: (res: unknown) => validateAddCompanyResult(res),
      // A synchronously-added (or already-tracked) company must appear in the
      // registry immediately. The 202 pending path adds nothing yet, so the
      // caller invalidates the tag itself once polling terminates in success.
      invalidatesTags: (result) =>
        result && result.status !== 'pending' ? ['UserCompanies'] : [],
    }),
    getSubmission: builder.query<SubmissionResult, string>({
      query: (id) => `/companies/submissions/${encodeURIComponent(id)}`,
      transformResponse: (res: unknown) => validateSubmissionResult(res),
    }),
  }),
});

export const {
  useGetUserCompaniesQuery,
  useAddCompanyMutation,
  useGetSubmissionQuery,
  useLazyGetSubmissionQuery,
} = userCompaniesApi;
