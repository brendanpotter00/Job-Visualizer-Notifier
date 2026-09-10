import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EnabledCompaniesSection } from '../../../components/saved-filters/EnabledCompaniesSection';
import { COMPANIES } from '../../../config/companies';

type MockEnabled = {
  ids: string[] | null;
  autoEnroll: boolean | null;
  loading: boolean;
  error: string | null;
  save: ReturnType<typeof vi.fn>;
  reload: ReturnType<typeof vi.fn>;
};

let mockEnabled: MockEnabled = {
  ids: null,
  autoEnroll: true,
  loading: false,
  error: null,
  save: vi.fn(),
  reload: vi.fn(),
};

vi.mock('../../../features/preferences/useEnabledCompanies', () => ({
  useEnabledCompanies: () => mockEnabled,
}));

// The real roster is ~190 companies, and every test that enters "Only these"
// renders a chip (with a logo) per company — far too slow for jsdom. Trim the
// roster to a handful; "Clear" is kept on purpose because it shares its name
// with the Clear button and once collided with it.
vi.mock('../../../config/companies', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../config/companies')>();
  const keep = new Set(['Adobe', 'Airbnb', 'Clear', 'Google', 'OpenAI', 'Stripe']);
  return { ...actual, COMPANIES: actual.COMPANIES.filter((c) => keep.has(c.name)) };
});

function resetMock(overrides: Partial<MockEnabled> = {}) {
  mockEnabled = {
    ids: null,
    autoEnroll: true,
    loading: false,
    error: null,
    save: vi.fn().mockResolvedValue(undefined),
    reload: vi.fn(),
    ...overrides,
  };
}

const getAllRadio = () => screen.getByRole('radio', { name: /all companies/i });
const getCustomRadio = () => screen.getByRole('radio', { name: /only these companies/i });
const getFilterInput = () => screen.getByRole('textbox', { name: /find a company/i });
const queryFilterInput = () => screen.queryByRole('textbox', { name: /find a company/i });
const getAutoEnrollCheckbox = () =>
  screen.getByRole('checkbox', { name: /auto-add new companies/i });
const queryAutoEnrollCheckbox = () =>
  screen.queryByRole('checkbox', { name: /auto-add new companies/i });
const getSaveButton = () => screen.getByRole('button', { name: /save companies/i });
const chip = (id: string) => screen.getByTestId(`company-chip-${id}`);
const queryChip = (id: string) => screen.queryByTestId(`company-chip-${id}`);
const getSummary = () => screen.getByTestId('saved-companies-summary');

describe('EnabledCompaniesSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetMock();
  });

  // ── initial state ─────────────────────────────────────────────────────

  it('shows a loading spinner when loading and ids are not yet loaded', () => {
    resetMock({ loading: true, ids: null });
    render(<EnabledCompaniesSection />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /all companies/i })).not.toBeInTheDocument();
  });

  it('starts in "All companies" mode with the grid hidden when ids is null', () => {
    resetMock({ ids: null });
    render(<EnabledCompaniesSection />);
    expect(getAllRadio()).toBeChecked();
    expect(getCustomRadio()).not.toBeChecked();
    expect(queryFilterInput()).not.toBeInTheDocument();
    expect(queryChip('airbnb')).not.toBeInTheDocument();
    expect(queryAutoEnrollCheckbox()).not.toBeInTheDocument();
    expect(getSummary()).toHaveTextContent('All companies');
    expect(getSaveButton()).toBeDisabled();
  });

  it('starts in "All companies" mode when the saved list is empty', () => {
    resetMock({ ids: [] });
    render(<EnabledCompaniesSection />);
    expect(getAllRadio()).toBeChecked();
    expect(queryFilterInput()).not.toBeInTheDocument();
  });

  it('starts in "Only these" mode with every company listed and the saved ones pressed', async () => {
    resetMock({ ids: ['stripe', 'airbnb'] });
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(getCustomRadio()).toBeChecked();
    });
    expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    expect(chip('stripe')).toHaveAttribute('aria-pressed', 'true');
    expect(chip('adobe')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getAllByTestId(/^company-chip-/)).toHaveLength(COMPANIES.length);
    expect(getAutoEnrollCheckbox()).toBeChecked();
    expect(getSummary()).toHaveTextContent('2 selected');
    expect(getSaveButton()).toBeDisabled();
  });

  it('ignores unknown company ids in saved state without crashing', async () => {
    resetMock({ ids: ['nope-not-a-company'] });
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(getCustomRadio()).toBeChecked();
    });
    expect(getSummary()).toHaveTextContent('0 selected');
    expect(getSaveButton()).toBeDisabled();
  });

  it('is not dirty when the saved list only differs in order', async () => {
    resetMock({ ids: ['stripe', 'airbnb'] });
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    });
    expect(getSaveButton()).toBeDisabled();
  });

  // ── mode switching ────────────────────────────────────────────────────

  it('switching to "Only these" reveals the grid but stays clean until a company is picked', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(getCustomRadio());

    expect(getFilterInput()).toBeInTheDocument();
    expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'false');
    expect(getAutoEnrollCheckbox()).toBeInTheDocument();
    expect(screen.getByText(/nothing picked yet/i)).toBeInTheDocument();
    // An empty explicit list persists exactly like "All companies", so nothing to save yet.
    expect(getSaveButton()).toBeDisabled();
  });

  it('switching a saved list to "All companies" saves an empty list', async () => {
    const saveMock = vi.fn().mockResolvedValue(undefined);
    resetMock({ ids: ['airbnb'], save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    });

    await user.click(getAllRadio());

    expect(queryChip('airbnb')).not.toBeInTheDocument();
    expect(getSummary()).toHaveTextContent('All companies');
    expect(getSaveButton()).toBeEnabled();

    await user.click(getSaveButton());
    await waitFor(() => {
      expect(saveMock).toHaveBeenCalledWith([], true);
    });
  });

  it('switching back to "Only these" restores the list that was there before', async () => {
    resetMock({ ids: ['airbnb'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    });

    await user.click(getAllRadio());
    await user.click(getCustomRadio());

    expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    expect(getSaveButton()).toBeDisabled();
  });

  // ── picking from the grid ─────────────────────────────────────────────

  it('clicking a chip selects it, updates the count, and enables Save', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(getCustomRadio());
    await user.click(chip('airbnb'));

    expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    expect(getSummary()).toHaveTextContent('1 selected');
    expect(screen.queryByText(/nothing picked yet/i)).not.toBeInTheDocument();
    expect(getSaveButton()).toBeEnabled();
  });

  it('clicking a selected chip removes it', async () => {
    resetMock({ ids: ['airbnb', 'stripe'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    });

    await user.click(chip('airbnb'));

    expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'false');
    expect(chip('stripe')).toHaveAttribute('aria-pressed', 'true');
    expect(getSummary()).toHaveTextContent('1 selected');
    expect(getSaveButton()).toBeEnabled();
  });

  it('the filter box narrows the grid without changing the selection', async () => {
    resetMock({ ids: ['stripe'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(chip('stripe')).toBeInTheDocument();
    });

    await user.type(getFilterInput(), 'airb');

    expect(chip('airbnb')).toBeInTheDocument();
    expect(queryChip('stripe')).not.toBeInTheDocument();
    expect(getSummary()).toHaveTextContent('1 selected');
    expect(getSaveButton()).toBeDisabled();
  });

  it('Enter in the filter box toggles the top match and clears the filter', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(getCustomRadio());
    await user.type(getFilterInput(), 'airb{Enter}');

    expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    expect(getFilterInput()).toHaveValue('');
    // The full grid is back, ready for the next name.
    expect(chip('stripe')).toBeInTheDocument();
  });

  it('shows a no-match message and Enter does nothing when the filter matches nothing', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(getCustomRadio());
    await user.type(getFilterInput(), 'zzzzzz{Enter}');

    expect(screen.getByText(/no companies match/i)).toBeInTheDocument();
    expect(getSummary()).toHaveTextContent('0 selected');
    expect(getSaveButton()).toBeDisabled();
  });

  it('Select all picks every company and Clear empties the list', async () => {
    resetMock({ ids: ['airbnb'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    });

    await user.click(screen.getByRole('button', { name: /select all companies/i }));
    expect(getSummary()).toHaveTextContent(`${COMPANIES.length} selected`);
    expect(chip('stripe')).toHaveAttribute('aria-pressed', 'true');
    expect(getSaveButton()).toBeEnabled();

    await user.click(screen.getByRole('button', { name: /clear selected companies/i }));
    expect(getSummary()).toHaveTextContent('0 selected');
    expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: /clear selected companies/i })).toBeDisabled();
  });

  // ── saving ────────────────────────────────────────────────────────────

  it('calls save with a canonicalized (sorted, deduped) id list', async () => {
    const saveMock = vi.fn().mockResolvedValue(undefined);
    resetMock({ ids: [], save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(getCustomRadio());
    await user.click(chip('stripe'));
    await user.click(chip('airbnb'));
    await user.click(getSaveButton());

    await waitFor(() => {
      expect(saveMock).toHaveBeenCalledWith(['airbnb', 'stripe'], true);
    });
  });

  it('shows "Saved." once the save lands and the hook reflects the new list', async () => {
    resetMock({ ids: [] });
    mockEnabled.save = vi.fn(async (ids: string[], autoEnroll: boolean) => {
      mockEnabled = { ...mockEnabled, ids, autoEnroll };
    });
    const user = userEvent.setup();
    const { rerender } = render(<EnabledCompaniesSection />);

    await user.click(getCustomRadio());
    await user.click(chip('airbnb'));
    await user.click(getSaveButton());
    rerender(<EnabledCompaniesSection />);

    await waitFor(() => {
      expect(screen.getByText('Saved.')).toBeInTheDocument();
    });
    expect(getSaveButton()).toBeDisabled();
  });

  it('shows an error when save rejects', async () => {
    const saveMock = vi.fn().mockRejectedValue(new Error('Network down'));
    resetMock({ ids: [], save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(getCustomRadio());
    await user.click(chip('airbnb'));
    await user.click(getSaveButton());

    await waitFor(() => {
      expect(screen.getByText(/network down/i)).toBeInTheDocument();
    });
  });

  it('surfaces a hook-level load error', () => {
    resetMock({ ids: [], error: 'Failed to load enabled companies' });
    render(<EnabledCompaniesSection />);
    expect(screen.getByText(/failed to load enabled companies/i)).toBeInTheDocument();
  });

  // ── auto-enroll checkbox ──────────────────────────────────────────────

  it('reflects autoEnroll=false from the hook as an unchecked box and stays clean', async () => {
    resetMock({ ids: ['airbnb'], autoEnroll: false });
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    });
    expect(getAutoEnrollCheckbox()).not.toBeChecked();
    expect(getSaveButton()).toBeDisabled();
  });

  it('toggling the checkbox alone makes the section dirty and saves autoEnroll=false', async () => {
    const saveMock = vi.fn().mockResolvedValue(undefined);
    resetMock({ ids: ['airbnb'], autoEnroll: true, save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(chip('airbnb')).toHaveAttribute('aria-pressed', 'true');
    });
    expect(getSaveButton()).toBeDisabled();

    await user.click(getAutoEnrollCheckbox());

    expect(getAutoEnrollCheckbox()).not.toBeChecked();
    expect(getSaveButton()).toBeEnabled();

    await user.click(getSaveButton());
    await waitFor(() => {
      expect(saveMock).toHaveBeenCalledWith(['airbnb'], false);
    });
  });

  it('starts checked when coming from "All companies", even if a stale false is stored', async () => {
    const saveMock = vi.fn().mockResolvedValue(undefined);
    resetMock({ ids: [], autoEnroll: false, save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    await user.click(getCustomRadio());

    expect(getAutoEnrollCheckbox()).toBeChecked();
    expect(getSaveButton()).toBeDisabled();

    await user.click(chip('airbnb'));
    await user.click(getSaveButton());
    await waitFor(() => {
      expect(saveMock).toHaveBeenCalledWith(['airbnb'], true);
    });
  });

  it('the checkbox is not offered in "All companies" mode', async () => {
    resetMock({ ids: ['airbnb'] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);
    await waitFor(() => {
      expect(getAutoEnrollCheckbox()).toBeInTheDocument();
    });

    await user.click(getAllRadio());

    expect(queryAutoEnrollCheckbox()).not.toBeInTheDocument();
  });
});
