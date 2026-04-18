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

describe('EnabledCompaniesSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetMock();
  });

  it('shows a loading spinner when loading and ids are not yet loaded', () => {
    resetMock({ loading: true, ids: null });
    render(<EnabledCompaniesSection />);

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByLabelText('Companies')).not.toBeInTheDocument();
  });

  it('renders the picker with no selected chips when ids is null', () => {
    resetMock({ ids: null, loading: false });
    render(<EnabledCompaniesSection />);

    expect(screen.getByLabelText('Companies')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
  });

  it('renders the picker with no selected chips when ids is empty', () => {
    resetMock({ ids: [], loading: false });
    render(<EnabledCompaniesSection />);

    expect(screen.getByLabelText('Companies')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^airbnb$/i })).not.toBeInTheDocument();
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

    const combo = screen.getByLabelText('Companies');
    await user.click(combo);
    await user.type(combo, 'Airbnb');
    await user.click(await screen.findByRole('option', { name: /airbnb/i }));

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

    expect(screen.getByLabelText('Companies')).toBeInTheDocument();
  });

  it('enables Save button when the draft differs from saved ids', async () => {
    resetMock({ ids: [] });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = screen.getByLabelText('Companies');
    await user.click(combo);
    await user.type(combo, 'Airbnb');
    const option = await screen.findByRole('option', { name: /airbnb/i });
    await user.click(option);

    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled();
  });

  it('calls save with a canonicalized (sorted, deduped) id list', async () => {
    const saveMock = vi.fn().mockResolvedValue(undefined);
    resetMock({ ids: [], save: saveMock });
    const user = userEvent.setup();
    render(<EnabledCompaniesSection />);

    const combo = screen.getByLabelText('Companies');
    await user.click(combo);
    await user.type(combo, 'Stripe');
    await user.click(await screen.findByRole('option', { name: /stripe/i }));
    await user.type(combo, 'Airbnb');
    await user.click(await screen.findByRole('option', { name: /airbnb/i }));

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

    const combo = screen.getByLabelText('Companies');
    await user.click(combo);
    await user.type(combo, 'Airbnb');
    await user.click(await screen.findByRole('option', { name: /airbnb/i }));

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

    const combo = screen.getByLabelText('Companies');
    await user.click(combo);
    await user.type(combo, 'Airbnb');
    await user.click(await screen.findByRole('option', { name: /airbnb/i }));

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

    await user.click(screen.getByRole('button', { name: /select all/i }));
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
});
