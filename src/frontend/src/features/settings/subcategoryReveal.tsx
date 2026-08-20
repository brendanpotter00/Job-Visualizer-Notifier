import { createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import { useGetPublicSettingsQuery } from '../jobs/jobsApi';

/**
 * The SWE-subcategory reveal flag, subscribed ONCE for the whole app.
 *
 * WHY A CONTEXT AND NOT JUST THE HOOK
 * -----------------------------------
 * `JobChipsSection` reads this flag and renders once per job card inside a
 * virtualized list. Calling `useGetPublicSettingsQuery` there directly would
 * mint one RTK Query subscription per rendered card — hundreds during a scroll,
 * each with its own lifecycle and its own removal timer. The provider takes the
 * single subscription; everything else reads a boolean off context.
 *
 * FAILS CLOSED, ALWAYS
 * --------------------
 * `false` while loading, `false` on any error, `false` when the endpoint 404s
 * (routine — Vercel deploys ahead of Railway), and `false` outside a provider.
 * The endpoint itself already resolves failures to data rather than errors; this
 * layer is the second half of the same rule, so a consumer can treat the return
 * value as a plain boolean and never as a tri-state.
 *
 * WHAT THE FLAG DOES NOT DO
 * -------------------------
 * It is a UI REVEAL switch and nothing more. The backend does not gate
 * `?subcategory=` on it, so flipping it off hides the CONTROL — it does not stop
 * a value a user already saved from filtering. That asymmetry is documented
 * rather than fixed: a clobber-on-mount guard would destroy legitimately saved
 * selections, and the flag is one-way in practice.
 *
 * CONSUMERS MUST STILL COMBINE IT WITH THE FACETS LENGTH:
 *     flag && (facets?.subcategories?.length ?? 0) > 0
 * The facets query is cached for an hour with no tags, so a warm pre-seed cache
 * plus a freshly-flipped flag would otherwise render a parent row that expands
 * into nothing.
 */
const SubcategoryRevealContext = createContext<boolean>(false);

export function SubcategoryRevealProvider({ children }: { children: ReactNode }) {
  // EXACTLY ONE subscription in the whole app. `refetchOnMountOrArgChange: 60`
  // pairs with the endpoint's `keepUnusedDataFor: 60` so a flip is picked up
  // within about a minute — or on the next navigation — without a page reload.
  const { data } = useGetPublicSettingsQuery(undefined, {
    refetchOnMountOrArgChange: 60,
  });

  return (
    <SubcategoryRevealContext.Provider value={data?.sweSubcategoriesEnabled === true}>
      {children}
    </SubcategoryRevealContext.Provider>
  );
}

/** `true` only when the backend says so. Never throws, never suspends. */
export function useSubcategoryRevealEnabled(): boolean {
  return useContext(SubcategoryRevealContext);
}
