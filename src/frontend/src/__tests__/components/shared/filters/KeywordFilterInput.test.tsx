import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { KeywordFilterInput } from '../../../../components/shared/filters/KeywordFilterInput';
import { SOFTWARE_ENGINEERING_TAGS } from '../../../../constants/tags';
import type { KeywordList, SearchTag } from '../../../../types';

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

const noop = {
  onAdd: vi.fn(),
  onRemove: vi.fn(),
  onToggleMode: vi.fn(),
  onClear: vi.fn(),
};

function renderInput(value: SearchTag[] | undefined, handlers: Partial<typeof noop> = {}) {
  const props = { ...noop, ...handlers };
  render(<KeywordFilterInput value={value} {...props} />);
  return props;
}

async function openDropdown() {
  const user = userEvent.setup();
  await user.click(screen.getByRole('combobox', { name: 'Keywords' }));
  return { user, listbox: await screen.findByRole('listbox') };
}

describe('KeywordFilterInput', () => {
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

  describe('typing free-form keywords', () => {
    it('adds a typed keyword on Enter (include mode by default)', async () => {
      const props = renderInput(undefined);
      const user = userEvent.setup();

      const input = screen.getByRole('combobox', { name: 'Keywords' });
      await user.click(input);
      await user.type(input, 'senior{enter}');

      expect(props.onAdd).toHaveBeenCalledTimes(1);
      expect(props.onAdd).toHaveBeenCalledWith({ text: 'senior', mode: 'include' });
    });

    it('parses a "-" prefix as an exclude tag', async () => {
      const props = renderInput(undefined);
      const user = userEvent.setup();

      const input = screen.getByRole('combobox', { name: 'Keywords' });
      await user.type(input, '-senior{enter}');

      expect(props.onAdd).toHaveBeenCalledWith({ text: 'senior', mode: 'exclude' });
    });

    it('typing + Enter NEVER applies a keyword list (the primary failure mode)', async () => {
      // Lists are present (anonymous → built-in SWE). Typing a keyword and
      // pressing Enter must add exactly that one tag and never merge a list.
      const props = renderInput(undefined);
      const user = userEvent.setup();

      const input = screen.getByRole('combobox', { name: 'Keywords' });
      await user.type(input, 'senior{enter}');

      expect(props.onAdd).toHaveBeenCalledTimes(1);
      expect(props.onAdd).toHaveBeenCalledWith({ text: 'senior', mode: 'include' });
    });
  });

  describe('anonymous users', () => {
    it('skips the auth-gated keyword-lists query', () => {
      renderInput(undefined);
      expect(mockUseGetKeywordListsQuery).toHaveBeenCalledWith(undefined, { skip: true });
    });

    it('offers the built-in SWE preset, a "None" row, and a sign-in CTA', async () => {
      renderInput(undefined);
      const { listbox } = await openDropdown();

      expect(within(listbox).getByRole('option', { name: 'None' })).toBeInTheDocument();
      expect(
        within(listbox).getByRole('option', { name: 'Software Engineering (default)' })
      ).toBeInTheDocument();
      expect(
        within(listbox).getByRole('option', { name: /sign in to create custom lists/i })
      ).toBeInTheDocument();
    });

    it('merges the SWE tags (one onAdd per tag) when the built-in preset is picked', async () => {
      const props = renderInput(undefined);
      const { user, listbox } = await openDropdown();

      await user.click(
        within(listbox).getByRole('option', { name: 'Software Engineering (default)' })
      );

      expect(props.onAdd).toHaveBeenCalledTimes(SWE_TAGS.length);
      SWE_TAGS.forEach((tag) => {
        expect(props.onAdd).toHaveBeenCalledWith(tag);
      });
      expect(props.onClear).not.toHaveBeenCalled();
    });

    it('triggers login (no tag change) when the sign-in CTA is clicked', async () => {
      const props = renderInput(undefined);
      const { user, listbox } = await openDropdown();

      await user.click(
        within(listbox).getByRole('option', { name: /sign in to create custom lists/i })
      );

      expect(mockLogin).toHaveBeenCalledTimes(1);
      expect(props.onAdd).not.toHaveBeenCalled();
      expect(props.onClear).not.toHaveBeenCalled();
    });
  });

  describe('authenticated users', () => {
    beforeEach(() => {
      mockAuthState.isAuthenticated = true;
      mockUseGetKeywordListsQuery.mockReturnValue({ data: [userList, serverBuiltin] });
    });

    it('fetches keyword lists (does not skip)', () => {
      renderInput(undefined);
      expect(mockUseGetKeywordListsQuery).toHaveBeenCalledWith(undefined, { skip: false });
    });

    it('renders user lists and the built-in, with no sign-in CTA', async () => {
      renderInput(undefined);
      const { listbox } = await openDropdown();

      expect(within(listbox).getByRole('option', { name: 'My PM roles' })).toBeInTheDocument();
      expect(
        within(listbox).getByRole('option', { name: 'Software Engineering (default)' })
      ).toBeInTheDocument();
      expect(
        within(listbox).queryByRole('option', { name: /sign in to create custom lists/i })
      ).not.toBeInTheDocument();
    });

    it("merges a user list's tags when selected", async () => {
      const props = renderInput(undefined);
      const { user, listbox } = await openDropdown();

      await user.click(within(listbox).getByRole('option', { name: 'My PM roles' }));

      expect(props.onAdd).toHaveBeenCalledTimes(userList.tags.length);
      expect(props.onAdd).toHaveBeenCalledWith(userList.tags[0]);
    });
  });

  describe('existing chips', () => {
    it("toggles a tag's mode when its chip is clicked", async () => {
      const props = renderInput([{ text: 'senior', mode: 'include' }]);
      const user = userEvent.setup();

      await user.click(screen.getByText('senior'));

      expect(props.onToggleMode).toHaveBeenCalledWith('senior');
    });

    it('removes a tag when its chip delete button is clicked', async () => {
      const props = renderInput([{ text: 'senior', mode: 'include' }]);
      const user = userEvent.setup();

      const chip = screen.getByText('senior').closest('.MuiChip-root') as HTMLElement;
      await user.click(within(chip).getByTestId('CancelIcon'));

      expect(props.onRemove).toHaveBeenCalledWith('senior');
    });

    it('clears all tags when "None" is selected', async () => {
      const props = renderInput([{ text: 'senior', mode: 'include' }]);
      const { user, listbox } = await openDropdown();

      await user.click(within(listbox).getByRole('option', { name: 'None' }));

      expect(props.onClear).toHaveBeenCalledTimes(1);
    });
  });
});
