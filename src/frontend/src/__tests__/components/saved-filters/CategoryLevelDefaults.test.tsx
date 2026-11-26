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
  it('renders NO child rows without onChangeSubcategory, even with the flag on and facets warm', async () => {
    // THE PRE-FE-SF-3 STATE, and the reason the props are optional. A caller
    // with nowhere to store a subcategory must not be offered the control: the
    // selection would be emitted and silently dropped.
    const store = await seededStore({ reveal: true });
    const user = userEvent.setup();
    // SWE ticked, so a child row would show here if the tree were on.
    renderPanel(store, { category: ['software_engineering'] }); // no onChangeSubcategory

    await user.click(screen.getByRole('combobox', { name: 'Job Category' }));
    const listbox = await screen.findByRole('listbox');

    expect(within(listbox).queryByTestId('facet-tree-chevron')).toBeNull();
    expect(within(listbox).queryByRole('button')).toBeNull();
    expect(within(listbox).queryByRole('option', { name: /Backend/ })).toBeNull();
  });

  it('renders NO child rows when the handler is present but the flag is OFF', async () => {
    const store = await seededStore({ reveal: false });
    const user = userEvent.setup();
    renderPanel(store, {
      category: ['software_engineering'],
      subcategory: [],
      onChangeSubcategory: vi.fn(),
    });

    await user.click(screen.getByRole('combobox', { name: 'Job Category' }));
    const listbox = await screen.findByRole('listbox');

    expect(within(listbox).queryByTestId('facet-tree-chevron')).toBeNull();
    expect(within(listbox).queryByRole('button')).toBeNull();
    expect(within(listbox).queryByRole('option', { name: /Backend/ })).toBeNull();
  });

  it('renders the tree when the handler is supplied AND the flag is on', async () => {
    const store = await seededStore({ reveal: true });
    const user = userEvent.setup();
    // SWE is already a saved default, so its specialties open with the menu.
    renderPanel(store, {
      category: ['software_engineering'],
      subcategory: [],
      onChangeSubcategory: vi.fn(),
    });

    await user.click(screen.getByRole('combobox', { name: 'Job Category' }));
    const listbox = await screen.findByRole('listbox');
    const swe = within(listbox).getByRole('option', { name: /Software Engineering/ });
    // The chevron is a cue, not a button.
    expect(within(swe).getByTestId('facet-tree-chevron')).toBeInTheDocument();
    expect(within(swe).queryByRole('button')).toBeNull();

    expect(within(listbox).getByRole('option', { name: /Backend/ })).toBeInTheDocument();
  });

  it('hides the specialties while SWE is not a saved default', async () => {
    const store = await seededStore({ reveal: true });
    const user = userEvent.setup();
    renderPanel(store, { subcategory: [], onChangeSubcategory: vi.fn() });

    await user.click(screen.getByRole('combobox', { name: 'Job Category' }));
    const listbox = await screen.findByRole('listbox');

    expect(
      within(listbox).getByRole('option', { name: 'Software Engineering, 2 specialties' })
    ).toBeInTheDocument();
    expect(within(listbox).queryByRole('option', { name: /Backend/ })).toBeNull();
  });

  it('ticking a revealed child calls BOTH handlers', async () => {
    const store = await seededStore({ reveal: true });
    const onChangeCategory = vi.fn();
    const onChangeSubcategory = vi.fn();
    const user = userEvent.setup();
    renderPanel(store, {
      category: ['software_engineering'],
      subcategory: [],
      onChangeCategory,
      onChangeSubcategory,
    });

    await user.click(screen.getByRole('combobox', { name: 'Job Category' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: /Backend/ }));

    expect(onChangeCategory).toHaveBeenCalledWith(['software_engineering']);
    expect(onChangeSubcategory).toHaveBeenCalledWith(['backend']);
  });

  it('unticking SWE clears its saved specialties in the same click', async () => {
    const store = await seededStore({ reveal: true });
    const onChangeCategory = vi.fn();
    const onChangeSubcategory = vi.fn();
    const user = userEvent.setup();
    renderPanel(store, {
      category: ['software_engineering'],
      subcategory: ['backend'],
      onChangeCategory,
      onChangeSubcategory,
    });

    await user.click(screen.getByRole('combobox', { name: 'Job Category' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: /Software Engineering/ }));

    expect(onChangeCategory).toHaveBeenCalledTimes(1);
    expect(onChangeCategory).toHaveBeenCalledWith([]);
    expect(onChangeSubcategory).toHaveBeenCalledTimes(1);
    expect(onChangeSubcategory).toHaveBeenCalledWith([]);
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
