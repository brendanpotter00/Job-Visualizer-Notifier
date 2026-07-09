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

    it('adds a typed keyword after a mouse list-pick (stale-highlight regression, C1)', async () => {
      // C1 (live-browser e2e): a mouse click on a list option is preceded by a
      // hover that fires onHighlightChange with reason 'mouse', arming
      // highlightedRef. If the ref is never reset, every LATER typed keyword +
      // Enter takes the `highlightedRef.current != null` defer-to-MUI branch;
      // MUI has no live highlight, fires createOption (ignored by handleChange),
      // and the typed keyword is SILENTLY DROPPED. Exact repro from the e2e:
      // open dropdown → click "Software Engineering (default)" → type a keyword
      // → Enter → the typed tag MUST be added, with no second list merge.
      const props = renderInput(undefined);
      const { user, listbox } = await openDropdown();

      // Mouse-pick the built-in list: merges its 6 tags AND (via the preceding
      // hover) arms the stale highlight the bug depends on.
      await user.click(
        within(listbox).getByRole('option', { name: 'Software Engineering (default)' })
      );
      expect(props.onAdd).toHaveBeenCalledTimes(SWE_TAGS.length);
      const callsAfterMerge = props.onAdd.mock.calls.length;

      // Now type a fresh keyword and press Enter.
      const input = screen.getByRole('combobox', { name: 'Keywords' });
      await user.type(input, 'beta{enter}');

      // The typed tag is added (the stale-highlight bug silently dropped it).
      expect(props.onAdd).toHaveBeenCalledWith({ text: 'beta', mode: 'include' });
      // Exactly one more onAdd (the typed tag) — no accidental second list merge.
      expect(props.onAdd).toHaveBeenCalledTimes(callsAfterMerge + 1);
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

    it('keyboard: ArrowDown-highlight + Enter merges the list and adds no stray typed tag', async () => {
      // Type a partial keyword, then arrow down to the first list option (a
      // list, since user lists are ordered first) and press Enter. The
      // highlighted-row branch in handleKeyDown defers to MUI's selectOption, so
      // the list is merged and the typed text is NOT added as a stray tag.
      const props = renderInput(undefined);
      const { user } = await openDropdown();

      await user.keyboard('prod');
      await user.keyboard('{ArrowDown}{Enter}');

      expect(props.onAdd).toHaveBeenCalledTimes(userList.tags.length);
      expect(props.onAdd).toHaveBeenCalledWith(userList.tags[0]);
      expect(props.onAdd).not.toHaveBeenCalledWith({ text: 'prod', mode: 'include' });
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

  describe('error surfacing (helperText channel)', () => {
    it('surfaces a keyword-lists fetch failure as error helperText', () => {
      // Ledger #1: an authed user's lists fetch can fail, otherwise silently
      // collapsing the dropdown to just "None". The failure must surface inline
      // through the TextField error/helperText channel (mirrors
      // AsyncMultiSelectAutocomplete). The shaped error matches what
      // extractErrorMessage consumes ({ data: { detail } }).
      mockAuthState.isAuthenticated = true;
      mockUseGetKeywordListsQuery.mockReturnValue({
        isError: true,
        error: { data: { detail: 'Failed to load keyword lists' } },
      });
      renderInput(undefined);

      const helperText = screen.getByText('Failed to load keyword lists');
      expect(helperText).toBeInTheDocument();
      // `Mui-error` lands on the helper text only when the TextField `error` prop
      // is set, so this also asserts the field is in its error state.
      expect(helperText).toHaveClass('Mui-error');
    });

    it('surfaces a sign-in failure as error helperText when login() rejects', async () => {
      // Ledger #2: the anonymous "Sign in to create custom lists" CTA calls
      // login(), which deliberately rethrows (pop-up-blocker / CSP / Auth0). The
      // component's `void login().catch(...)` surfaces the rejection inline AND
      // handles it, so no unhandled rejection leaks. A message-less Error falls
      // back to the default copy.
      mockLogin.mockRejectedValueOnce(new Error());
      renderInput(undefined);
      const { user, listbox } = await openDropdown();

      await user.click(
        within(listbox).getByRole('option', { name: /sign in to create custom lists/i })
      );

      expect(mockLogin).toHaveBeenCalledTimes(1);
      const helperText = await screen.findByText('Sign-in failed. Please try again.');
      expect(helperText).toHaveClass('Mui-error');
    });
  });

  describe('active-list indicator (checkmark)', () => {
    it("marks a list with a checkmark when the current tags equal its tags (order-insensitive)", async () => {
      // Seed the current tags equal to the built-in SWE list but reversed, to
      // prove the match is order-insensitive (tagsEqual → isActive → CheckIcon).
      const reversed = [...SWE_TAGS].reverse();
      renderInput(reversed);
      const { listbox } = await openDropdown();

      const sweOption = within(listbox).getByRole('option', {
        name: 'Software Engineering (default)',
      });
      expect(within(sweOption).getByTestId('CheckIcon')).toBeInTheDocument();
    });

    it('shows no checkmark when the current tags differ from every list', async () => {
      renderInput([{ text: 'unrelated keyword', mode: 'include' }]);
      const { listbox } = await openDropdown();

      const sweOption = within(listbox).getByRole('option', {
        name: 'Software Engineering (default)',
      });
      expect(within(sweOption).queryByTestId('CheckIcon')).not.toBeInTheDocument();
    });
  });
});
