import { describe, it, expect, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, createTestStore } from '../../../test/testUtils';
import { CategoryLevelDefaults } from '../../../components/saved-filters/CategoryLevelDefaults';
import { SubcategoryRevealProvider } from '../../../features/settings/subcategoryReveal';
import { jobsApi } from '../../../features/jobs/jobsApi';
import type { JobFacets } from '../../../types';

const FACETS: JobFacets = {
  categories: [
    { slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0 },
    { slug: 'growth', label: 'Growth', sortOrder: 1 },
  ],
  levels: [{ slug: 'senior', label: 'Senior', sortOrder: 0, parentSlug: null }],
  subcategories: [
    { slug: 'backend', label: 'Backend', sortOrder: 1, parentSlug: 'software_engineering' },
    { slug: 'frontend', label: 'Frontend', sortOrder: 6, parentSlug: 'software_engineering' },
  ],
};

const SAVE_PROPS = {
  dirty: false,
  saving: false,
  success: false,
  error: null,
  onSave: vi.fn(),
};

async function seededStore({ reveal }: { reveal: boolean }) {
  const store = createTestStore();
  await store.dispatch(jobsApi.util.upsertQueryData('getFacets', undefined, FACETS));
  await store.dispatch(
    jobsApi.util.upsertQueryData('getPublicSettings', undefined, {
      sweSubcategoriesEnabled: reveal,
    })
  );
  return store;
}

/**
 * `renderWithProviders` takes NO `wrapper` option — its `CustomRenderOptions`
 * is `Omit<RenderOptions, 'wrapper'>` — so the reveal provider wraps the
 * ELEMENT, matching how `App.tsx` mounts it.
 */
function renderPanel(
  store: ReturnType<typeof createTestStore>,
  props: Partial<Parameters<typeof CategoryLevelDefaults>[0]> = {}
) {
  return renderWithProviders(
    <SubcategoryRevealProvider>
      <CategoryLevelDefaults
        category={[]}
        level={[]}
        onChangeCategory={vi.fn()}
        onChangeLevel={vi.fn()}
        {...SAVE_PROPS}
        {...props}
      />
    </SubcategoryRevealProvider>,
    { store }
  );
}

describe('CategoryLevelDefaults — the subcategory tree', () => {
  it('renders NO chevron without onChangeSubcategory, even with the flag on and facets warm', async () => {
    // THE PRE-FE-SF-3 STATE, and the reason the props are optional. A caller
    // with nowhere to store a subcategory must not be offered the control: the
    // selection would be emitted and silently dropped.
    const store = await seededStore({ reveal: true });
    const user = userEvent.setup();
    renderPanel(store); // no onChangeSubcategory

    await user.click(screen.getByRole('combobox', { name: 'Job category' }));
    const listbox = await screen.findByRole('listbox');

    expect(within(listbox).queryByRole('button')).toBeNull();
    expect(within(listbox).queryByRole('option', { name: /Backend/ })).toBeNull();
  });

  it('renders NO chevron when the handler is present but the flag is OFF', async () => {
    const store = await seededStore({ reveal: false });
    const user = userEvent.setup();
    renderPanel(store, { subcategory: [], onChangeSubcategory: vi.fn() });

    await user.click(screen.getByRole('combobox', { name: 'Job category' }));
    const listbox = await screen.findByRole('listbox');

    expect(within(listbox).queryByRole('button')).toBeNull();
  });

  it('renders the tree when the handler is supplied AND the flag is on', async () => {
    const store = await seededStore({ reveal: true });
    const user = userEvent.setup();
    renderPanel(store, { subcategory: [], onChangeSubcategory: vi.fn() });

    await user.click(screen.getByRole('combobox', { name: 'Job category' }));
    const listbox = await screen.findByRole('listbox');
    const swe = within(listbox).getByRole('option', { name: /Software Engineering/ });

    await user.click(within(swe).getByRole('button'));
    expect(within(listbox).getByRole('option', { name: /Backend/ })).toBeInTheDocument();
  });

  it('ticking a child calls BOTH handlers, auto-checking the parent', async () => {
    const store = await seededStore({ reveal: true });
    const onChangeCategory = vi.fn();
    const onChangeSubcategory = vi.fn();
    const user = userEvent.setup();
    renderPanel(store, { subcategory: [], onChangeCategory, onChangeSubcategory });

    await user.click(screen.getByRole('combobox', { name: 'Job category' }));
    const listbox = await screen.findByRole('listbox');
    const swe = within(listbox).getByRole('option', { name: /Software Engineering/ });
    await user.click(within(swe).getByRole('button'));
    await user.click(within(listbox).getByRole('option', { name: /Backend/ }));

    expect(onChangeCategory).toHaveBeenCalledWith(['software_engineering']);
    expect(onChangeSubcategory).toHaveBeenCalledWith(['backend']);
  });

  it('leaves the Level control alone', async () => {
    const store = await seededStore({ reveal: true });
    const user = userEvent.setup();
    renderPanel(store, { subcategory: [], onChangeSubcategory: vi.fn() });

    await user.click(screen.getByRole('combobox', { name: 'Level' }));
    const listbox = await screen.findByRole('listbox');

    expect(within(listbox).getByRole('option', { name: 'Senior' })).toBeInTheDocument();
    expect(within(listbox).queryByRole('button')).toBeNull();
  });
});
