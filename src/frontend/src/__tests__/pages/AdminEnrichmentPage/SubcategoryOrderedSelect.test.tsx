import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SubcategoryOrderedSelect } from '../../../pages/AdminEnrichmentPage/components/SubcategoryOrderedSelect';
import type { FacetOption } from '../../../types';

/**
 * The control is a pure props-driven component (no RTK Query / store), so it
 * renders directly with fixture options — the JobDescriptionDialog test idiom.
 */
const OPTIONS: FacetOption[] = [
  { slug: 'backend', label: 'Backend', sortOrder: 1, parentSlug: 'software_engineering' },
  { slug: 'frontend', label: 'Frontend', sortOrder: 6, parentSlug: 'software_engineering' },
  { slug: 'mobile', label: 'Mobile', sortOrder: 10, parentSlug: 'software_engineering' },
];

async function openMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('combobox', { name: /subcategories/i }));
}

describe('SubcategoryOrderedSelect', () => {
  it('⚠ emits selections in CLICK order, NOT alphabetical order', async () => {
    // THE most valuable assertion in this file. Index 0 is the PRIMARY
    // specialty — it drives the job card's first chip and the eval's primary
    // accuracy metric. MUI's `Autocomplete multiple` appends in click order,
    // which is undocumented behaviour this test pins. An alphabetical result
    // here would be silently wrong in exactly the way nobody notices.
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <SubcategoryOrderedSelect options={OPTIONS} value={[]} onChange={onChange} />
    );

    await openMenu(user);
    await user.click(screen.getByRole('option', { name: /frontend/i }));
    expect(onChange).toHaveBeenLastCalledWith(['frontend']);

    rerender(
      <SubcategoryOrderedSelect options={OPTIONS} value={['frontend']} onChange={onChange} />
    );
    await user.click(screen.getByRole('option', { name: /backend/i }));

    expect(onChange).toHaveBeenLastCalledWith(['frontend', 'backend']);
    expect(onChange).not.toHaveBeenLastCalledWith(['backend', 'frontend']);
  });

  it('disables every remaining option once two are chosen', async () => {
    const user = userEvent.setup();
    render(
      <SubcategoryOrderedSelect
        options={OPTIONS}
        value={['backend', 'frontend']}
        onChange={vi.fn()}
      />
    );

    await openMenu(user);
    const third = screen.getByRole('option', { name: /mobile/i });
    expect(third).toHaveAttribute('aria-disabled', 'true');
    // The two already selected stay clickable, so a mistake is reversible.
    expect(screen.getByRole('option', { name: /backend/i })).not.toHaveAttribute(
      'aria-disabled',
      'true'
    );
  });

  it('renders the primary chip filled and the secondary outlined', () => {
    const { container } = render(
      <SubcategoryOrderedSelect
        options={OPTIONS}
        value={['backend', 'frontend']}
        onChange={vi.fn()}
      />
    );
    const chips = Array.from(container.querySelectorAll('.MuiChip-root'));
    expect(chips).toHaveLength(2);
    expect(chips[0].className).toMatch(/MuiChip-filled/);
    expect(chips[1].className).toMatch(/MuiChip-outlined/);
  });

  it('renders labels from the LIVE options, falling back to the raw slug', () => {
    render(
      <SubcategoryOrderedSelect
        options={OPTIONS}
        value={['backend', 'not_in_facets']}
        onChange={vi.fn()}
      />
    );
    expect(screen.getByText('Backend')).toBeInTheDocument();
    expect(screen.getByText('not_in_facets')).toBeInTheDocument();
  });

  it('renders an empty control when facets carry no subcategories', async () => {
    // A phase-1 backend serves an EMPTY dimension. The control must render
    // with nothing to pick rather than falling back to a hardcoded list that
    // the database would reject.
    const user = userEvent.setup();
    render(<SubcategoryOrderedSelect options={[]} value={[]} onChange={vi.fn()} />);

    await openMenu(user);
    expect(screen.queryAllByRole('option')).toHaveLength(0);
  });
});
