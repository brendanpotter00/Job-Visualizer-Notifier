import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EnabledCompaniesSection } from '../../../components/account/EnabledCompaniesSection';
import { COMPANIES } from '../../../config/companies';

type MockEnabled = {
  ids: string[] | null;
  loading: boolean;
  error: string | null;
  save: ReturnType<typeof vi.fn>;
  reload: ReturnType<typeof vi.fn>;
};

let mockEnabled: MockEnabled = {
  ids: null,
  loading: false,
  error: null,
  save: vi.fn(),
  reload: vi.fn(),
};

vi.mock('../../../features/preferences/useEnabledCompanies', () => ({
  useEnabledCompanies: () => mockEnabled,
}));

function resetMock(overrides: Partial<MockEnabled> = {}) {
  mockEnabled = {
    ids: null,
    loading: false,
    error: null,
    save: vi.fn().mockResolvedValue(undefined),
    reload: vi.fn(),
    ...overrides,
  };
}

function getSearchCombobox(): HTMLElement {
  return screen.getByRole('combobox', { name: /search companies/i });
}

describe('EnabledCompaniesSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetMock();
  });

  it('shows a loading spinner when loading and ids are not yet loaded', () => {
    resetMock({ loading: true, ids: null });
    render(<EnabledCompaniesSection />);

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(
      screen.queryByRole('combobox', { name: /search companies/i })
    ).not.toBeInTheDocument();
  });

  it('renders the picker with no selected chips when ids is null', () => {
    resetMock({ ids: null, loading: false });
    render(<EnabledCompaniesSection />);

    expect(getSearchCombobox()).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
  });

  it('renders the picker with no selected chips when ids is empty', () => {
    resetMock({ ids: [], loading: false });
    render(<EnabledCompaniesSection />);

    expect(getSearchCombobox()).toBeInTheDocument();
    expect(screen.queryByTestId('selected-chip-Airbnb')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
  });

  it('renders saved ids as chips with display names', async () => {
    resetMock({ ids: ['airbnb'] });
    render(<EnabledCompaniesSection />);

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });
  });

  it('shows the empty-state copy and zero count when nothing is selected', () => {
    resetMock({ ids: [], loading: false });
    render(<EnabledCompaniesSection />);

    expect(screen.getByTestId('selected-count')).toHaveTextContent('0');
    expect(
      screen.getByText(/no companies selected\. you'll see postings from all companies\./i)
    ).toBeInTheDocument();
  });

  it('updates the selected-count chip when selections change', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    expect(screen.getByTestId('selected-count')).toHaveTextContent('0');

    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'Airbnb');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(screen.getByTestId('selected-count')).toHaveTextContent('1');
    });
    expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
  });

  it('removes a selection when the chip delete icon is clicked', async () => {
    resetMock({ ids: ['airbnb', 'stripe'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    const chip = screen.getByTestId('selected-chip-Airbnb');
    const deleteIcon = chip.querySelector('svg');
    expect(deleteIcon).not.toBeNull();
    await user.click(deleteIcon!);

    expect(screen.queryByTestId('selected-chip-Airbnb')).not.toBeInTheDocument();
    expect(screen.getByTestId('selected-chip-Stripe')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled();
  });

  it('disables the Clear button while the draft is empty', () => {
    resetMock({ ids: [] });
    render(<EnabledCompaniesSection />);

    expect(screen.getByRole('button', { name: /^clear$/i })).toBeDisabled();
  });

  it('ignores unknown company ids in saved state without crashing', () => {
    resetMock({ ids: ['some-deleted-company'] });
    render(<EnabledCompaniesSection />);

    expect(getSearchCombobox()).toBeInTheDocument();
  });

  it('enables Save button when the draft differs from saved ids', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'Airbnb');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled();
  });

  it('calls save with a canonicalized (sorted, deduped) id list', async () => {
    const saveMock = vi.fn().mockResolvedValue(undefined);
    resetMock({ ids: [], save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'Stripe');
    await user.keyboard('{Enter}');
    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Stripe')).toBeInTheDocument();
    });
    await user.type(combo, 'Airbnb');
    await user.keyboard('{Enter}');
    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(saveMock).toHaveBeenCalledWith(['airbnb', 'stripe']);
    });
  });

  it('shows success alert after a successful save', async () => {
    const saveMock = vi.fn().mockResolvedValue(undefined);
    resetMock({ ids: [], save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'Airbnb');
    await user.keyboard('{Enter}');
    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.getByText('Preferences saved.')).toBeInTheDocument();
    });
  });

  it('shows error alert when save rejects', async () => {
    const saveMock = vi.fn().mockRejectedValue(new Error('Failed to save enabled companies (500)'));
    resetMock({ ids: [], save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'Airbnb');
    await user.keyboard('{Enter}');
    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.getByText('Failed to save enabled companies (500)')).toBeInTheDocument();
    });
  });

  it('Select All populates the draft with every company id', async () => {
    const saveMock = vi.fn().mockResolvedValue(undefined);
    resetMock({ ids: [], save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(screen.getByRole('button', { name: /^select all$/i }));
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    const expectedIds = [...COMPANIES.map((c) => c.id)].sort();
    await waitFor(() => {
      expect(saveMock).toHaveBeenCalledWith(expectedIds);
    });
  });

  it('Clear empties the draft and makes it dirty relative to a non-empty saved list', async () => {
    resetMock({ ids: ['airbnb'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /^clear$/i }));

    expect(screen.queryByTestId('selected-chip-Airbnb')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled();
  });

  it('treats saved and draft as equal regardless of order (not dirty when order differs)', async () => {
    resetMock({ ids: ['stripe', 'airbnb'] });
    render(<EnabledCompaniesSection />);

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Stripe')).toBeInTheDocument();
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
  });

  // ---------------------------------------------------------------------
  // New-behavior tests: search-add flow, hide-already-selected, accordion,
  // chip grid toggles, grid-panel sync, keyboard navigation.
  // ---------------------------------------------------------------------

  it('Enter commits top match and clears the input', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = getSearchCombobox() as HTMLInputElement;
    await user.click(combo);
    await user.type(combo, 'air');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });
    expect(combo.value).toBe('');
  });

  it('supports sequential fast-add via Enter', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'strip');
    await user.keyboard('{Enter}');
    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Stripe')).toBeInTheDocument();
    });

    await user.type(combo, 'airb');
    await user.keyboard('{Enter}');
    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    expect(screen.getByTestId('selected-count')).toHaveTextContent('2');
  });

  it('pressing Enter with zero matches does not add anything', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'zzzzzz');
    await user.keyboard('{Enter}');

    expect(screen.getByTestId('selected-count')).toHaveTextContent('0');
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
  });

  it('hides already-selected companies from the search dropdown', async () => {
    resetMock({ ids: ['airbnb'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'Airbnb');

    // The input has "Airbnb" typed, but Airbnb is already selected and
    // therefore filtered out. Expect the "No companies match" fallback.
    await waitFor(() => {
      expect(screen.getByText(/no companies match/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole('option', { name: /^airbnb$/i })).not.toBeInTheDocument();
  });

  it('accordion is collapsed by default and expands to reveal the chip grid', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    expect(screen.queryByTestId('browse-chip-Airbnb')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /browse and select all companies/i }));

    await waitFor(() => {
      expect(screen.getByTestId('browse-chip-Airbnb')).toBeInTheDocument();
    });
  });

  it('clicking a chip in the grid toggles selection on', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(screen.getByRole('button', { name: /browse and select all companies/i }));
    const gridChip = await screen.findByTestId('browse-chip-Airbnb');
    await user.click(gridChip);

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled();
  });

  it('clicking an already-selected chip in the grid removes it', async () => {
    resetMock({ ids: ['airbnb'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /browse and select all companies/i }));
    const gridChip = await screen.findByTestId('browse-chip-Airbnb');
    await user.click(gridChip);

    await waitFor(() => {
      expect(screen.queryByTestId('selected-chip-Airbnb')).not.toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled();
  });

  it('grid chips reflect selection visually via aria-pressed', async () => {
    resetMock({ ids: ['airbnb'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(screen.getByRole('button', { name: /browse and select all companies/i }));

    const airbnbChip = await screen.findByTestId('browse-chip-Airbnb');
    expect(airbnbChip).toHaveAttribute('aria-pressed', 'true');

    const stripeChip = await screen.findByTestId('browse-chip-Stripe');
    expect(stripeChip).toHaveAttribute('aria-pressed', 'false');
  });

  it('selected-panel delete and grid stay in sync', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    // Add Airbnb via the search input.
    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'air');
    await user.keyboard('{Enter}');
    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });

    // Expand grid, verify pressed.
    await user.click(screen.getByRole('button', { name: /browse and select all companies/i }));
    const gridChip = await screen.findByTestId('browse-chip-Airbnb');
    expect(gridChip).toHaveAttribute('aria-pressed', 'true');

    // Delete from the selected panel.
    const selectedChip = screen.getByTestId('selected-chip-Airbnb');
    const deleteIcon = selectedChip.querySelector('svg');
    expect(deleteIcon).not.toBeNull();
    await user.click(deleteIcon!);

    // Grid chip should now be unpressed.
    await waitFor(() => {
      expect(screen.getByTestId('browse-chip-Airbnb')).toHaveAttribute('aria-pressed', 'false');
    });
  });

  it('ArrowDown + Enter commits the second alphabetical option', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = getSearchCombobox();
    await user.click(combo);
    await user.type(combo, 'a');
    // Wait for the options list to be visible.
    await screen.findByRole('option', { name: /^adobe$/i });

    // With autoHighlight pre-highlighting the first option, MUI's
    // Autocomplete has a quirk where the first ArrowDown press nudges the
    // active descendant onto the already-highlighted row rather than
    // stepping past it. A second ArrowDown advances to the next option.
    // Rather than asserting on that specific behavior, we lock the intent
    // via aria-activedescendant below — the W3C-standard pointer from an
    // editable combobox to its currently-highlighted option. That
    // decouples this test from MUI's internal highlight tracking (class
    // names, aria-selected on options, etc.) while still proving the
    // Enter-press commits the row we think it will.
    await user.keyboard('{ArrowDown}{ArrowDown}');
    const airbnbOption = screen.getByRole('option', { name: /airbnb/i });
    expect(combo).toHaveAttribute('aria-activedescendant', airbnbOption.id);
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(screen.getByTestId('selected-chip-Airbnb')).toBeInTheDocument();
    });
  });
});
