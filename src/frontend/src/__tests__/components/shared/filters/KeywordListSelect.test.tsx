import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { KeywordListSelect } from '../../../../components/shared/filters/KeywordListSelect';
import { SOFTWARE_ENGINEERING_TAGS } from '../../../../constants/tags';
import type { KeywordList } from '../../../../types';

const mockLogin = vi.fn(() => Promise.resolve());
let mockAuthState = {
  isEnabled: true,
  isAuthenticated: false,
  isLoading: false,
  login: mockLogin,
  logout: vi.fn(),
  getToken: vi.fn(),
  user: null,
};

vi.mock('../../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

const mockUseGetKeywordListsQuery = vi.fn();
vi.mock('../../../../features/savedFilters/savedFiltersApi', () => ({
  useGetKeywordListsQuery: (...args: unknown[]) => mockUseGetKeywordListsQuery(...args),
}));

const SWE_TAGS = SOFTWARE_ENGINEERING_TAGS.map((tag) => ({ ...tag }));

const userList: KeywordList = {
  id: 'list-1',
  name: 'My PM roles',
  tags: [{ text: 'product manager', mode: 'include' }],
  isBuiltin: false,
  position: 0,
};

const serverBuiltin: KeywordList = {
  id: 'builtin-swe',
  name: 'Software Engineering',
  tags: SWE_TAGS,
  isBuiltin: true,
  position: 0,
};

async function openDropdown() {
  const user = userEvent.setup();
  await user.click(screen.getByRole('combobox', { name: 'Keyword list' }));
  return { user, listbox: await screen.findByRole('listbox') };
}

describe('KeywordListSelect', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLogin.mockResolvedValue(undefined);
    mockAuthState = {
      isEnabled: true,
      isAuthenticated: false,
      isLoading: false,
      login: mockLogin,
      logout: vi.fn(),
      getToken: vi.fn(),
      user: null,
    };
    mockUseGetKeywordListsQuery.mockReturnValue({ data: undefined });
  });

  describe('anonymous users', () => {
    it('skips the auth-gated keyword-lists query', () => {
      render(<KeywordListSelect value={undefined} onChange={vi.fn()} />);
      expect(mockUseGetKeywordListsQuery).toHaveBeenCalledWith(undefined, { skip: true });
    });

    it('offers the built-in SWE preset and a sign-in CTA', async () => {
      render(<KeywordListSelect value={undefined} onChange={vi.fn()} />);
      const { listbox } = await openDropdown();

      expect(within(listbox).getByRole('option', { name: 'None' })).toBeInTheDocument();
      expect(
        within(listbox).getByRole('option', { name: 'Software Engineering (default)' })
      ).toBeInTheDocument();
      expect(
        within(listbox).getByRole('option', { name: /sign in to create custom lists/i })
      ).toBeInTheDocument();
    });

    it('applies the SWE tags when the built-in preset is selected', async () => {
      const onChange = vi.fn();
      render(<KeywordListSelect value={undefined} onChange={onChange} />);
      const { user, listbox } = await openDropdown();

      await user.click(
        within(listbox).getByRole('option', { name: 'Software Engineering (default)' })
      );

      expect(onChange).toHaveBeenCalledTimes(1);
      expect(onChange).toHaveBeenCalledWith(SWE_TAGS);
    });

    it('triggers login without changing the selection when the CTA is clicked', async () => {
      const onChange = vi.fn();
      render(<KeywordListSelect value={undefined} onChange={onChange} />);
      const { user, listbox } = await openDropdown();

      await user.click(
        within(listbox).getByRole('option', { name: /sign in to create custom lists/i })
      );

      expect(mockLogin).toHaveBeenCalledTimes(1);
      expect(onChange).not.toHaveBeenCalled();
    });
  });

  describe('authenticated users', () => {
    beforeEach(() => {
      mockAuthState.isAuthenticated = true;
      mockUseGetKeywordListsQuery.mockReturnValue({ data: [userList, serverBuiltin] });
    });

    it('fetches keyword lists (does not skip)', () => {
      render(<KeywordListSelect value={undefined} onChange={vi.fn()} />);
      expect(mockUseGetKeywordListsQuery).toHaveBeenCalledWith(undefined, { skip: false });
    });

    it('renders user lists and the built-in, with no sign-in CTA', async () => {
      render(<KeywordListSelect value={undefined} onChange={vi.fn()} />);
      const { listbox } = await openDropdown();

      expect(within(listbox).getByRole('option', { name: 'My PM roles' })).toBeInTheDocument();
      expect(
        within(listbox).getByRole('option', { name: 'Software Engineering (default)' })
      ).toBeInTheDocument();
      expect(
        within(listbox).queryByRole('option', { name: /sign in to create custom lists/i })
      ).not.toBeInTheDocument();
    });

    it('applies a user list\'s tags when selected', async () => {
      const onChange = vi.fn();
      render(<KeywordListSelect value={undefined} onChange={onChange} />);
      const { user, listbox } = await openDropdown();

      await user.click(within(listbox).getByRole('option', { name: 'My PM roles' }));

      expect(onChange).toHaveBeenCalledWith(userList.tags);
    });
  });

  it('clears tags when "None" is selected', async () => {
    const onChange = vi.fn();
    render(
      <KeywordListSelect value={[{ text: 'senior', mode: 'include' }]} onChange={onChange} />
    );
    const { user, listbox } = await openDropdown();

    await user.click(within(listbox).getByRole('option', { name: 'None' }));

    expect(onChange).toHaveBeenCalledWith(undefined);
  });
});
