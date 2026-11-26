import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import { Provider } from 'react-redux';
import userEvent from '@testing-library/user-event';
import { CompanySelector } from '../../../../components/companies-page/CompanySelector/CompanySelector';
import { createTestStore, findListboxOption } from '../../../../test/testUtils';
import { PUBLIC_COMPANY_OPTIONS } from '../../../../features/userCompanies/effectiveCompanies';
import { setSelectedATS, setSelectedCompanyId } from '../../../../features/app/appSlice';
import { ATSConstants } from '../../../../api/types';

/**
 * A fresh store per test. The app's singleton `store` would carry one test's
 * pick into the next, and "SpaceX is selected" is what most of these start from.
 */
function renderSelector(selectedCompanyId?: string) {
  const store = createTestStore(
    selectedCompanyId
      ? {
          app: { selectedCompanyId, selectedATS: ATSConstants.BackendScraper, isInitialized: true },
        }
      : {}
  );
  render(
    <Provider store={store}>
      <CompanySelector />
    </Provider>
  );
  return store;
}

function companyInput() {
  return screen.getByRole('combobox', { name: 'Company' });
}

/** Visible names of every row in the open list, top to bottom. */
function optionNames() {
  return within(screen.getByRole('listbox'))
    .getAllByRole('option')
    .map((option) => option.textContent);
}

/** Every roster name containing `query`, case-insensitively, in list order. */
function rosterNamesContaining(query: string) {
  return PUBLIC_COMPANY_OPTIONS.filter((company) =>
    company.name.toLowerCase().includes(query.toLowerCase())
  ).map((company) => company.name);
}

describe('CompanySelector', () => {
  it('renders a combobox named "Company" on the company-selector input', () => {
    renderSelector();

    const input = companyInput();
    expect(input).toHaveAttribute('id', 'company-selector');
    // The label is wired to the input with `for`, under the id it always had.
    const label = document.getElementById('company-selector-label');
    expect(label).toHaveTextContent('Company');
    expect(label).toHaveAttribute('for', 'company-selector');
  });

  it('shows the selected company name in the field', () => {
    renderSelector();
    // Default is SpaceX
    expect(companyInput()).toHaveValue('SpaceX');
  });

  it('opens the full alphabetical list on click, like the old dropdown', async () => {
    const user = userEvent.setup();
    renderSelector();

    await user.click(companyInput());

    // The field already reads "SpaceX", but that must not filter the list down
    // to SpaceX: an untouched field shows every company.
    expect(await findListboxOption('SpaceX')).toHaveAccessibleName('SpaceX');
    expect(await findListboxOption('Anduril')).toHaveAccessibleName('Anduril');
    expect(optionNames()).toEqual(PUBLIC_COMPANY_OPTIONS.map((company) => company.name));
  });

  it('opens the list on keyboard focus too', async () => {
    const user = userEvent.setup();
    renderSelector();

    await user.tab();

    expect(companyInput()).toHaveFocus();
    expect(await screen.findByRole('listbox')).toBeInTheDocument();
  });

  it('narrows the list to names containing the typed text, ignoring case', async () => {
    const user = userEvent.setup();
    renderSelector();
    const input = companyInput();

    await user.click(input);
    await user.clear(input);
    await user.type(input, 'SAR');

    // Derived from the roster rather than hard-coded, so a company added later
    // whose name contains "sar" doesn't break this; Saronic pins that it works.
    const expected = rosterNamesContaining('sar');
    expect(expected).toContain('Saronic');
    await waitFor(() => expect(optionNames()).toEqual(expected));
    expect(optionNames()).not.toContain('SpaceX');
  });

  it('matches anywhere in the name, not just the start', async () => {
    const user = userEvent.setup();
    renderSelector();
    const input = companyInput();

    await user.click(input);
    await user.clear(input);
    await user.type(input, 'ronic');

    const expected = rosterNamesContaining('ronic');
    expect(expected).toContain('Saronic');
    await waitFor(() => expect(optionNames()).toEqual(expected));
  });

  it('says so when nothing matches', async () => {
    const user = userEvent.setup();
    renderSelector();
    const input = companyInput();

    await user.click(input);
    await user.clear(input);
    await user.type(input, 'zzqqxxnomatch');

    expect(await screen.findByText('No companies match')).toBeInTheDocument();
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
  });

  it('has no clear button, before or after typing', async () => {
    const user = userEvent.setup();
    renderSelector();
    const input = companyInput();

    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument();

    await user.click(input);
    await user.clear(input);
    await user.type(input, 'an');

    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument();
    // Emptying the field is not a way to deselect: the page always has a company.
    expect(input).toHaveValue('an');
  });

  it('puts the selected name back when the field is left without a pick', async () => {
    const user = userEvent.setup();
    const store = renderSelector();
    const input = companyInput();

    await user.click(input);
    await user.clear(input);
    await user.type(input, 'anth');
    await user.tab();

    expect(input).toHaveValue('SpaceX');
    expect(store.getState().app.selectedCompanyId).toBe('spacex');
    await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument());
  });

  it('changes selected company when option is clicked', async () => {
    const user = userEvent.setup();
    const store = renderSelector();

    await user.click(companyInput());
    await user.click(await findListboxOption('Anduril'));

    await waitFor(() => {
      expect(store.getState().app.selectedCompanyId).toBe('andurilindustries');
    });
    expect(companyInput()).toHaveValue('Anduril');
  });

  it('lets a second company be searched straight after a mouse pick', async () => {
    const user = userEvent.setup();
    const store = renderSelector();
    const input = companyInput();

    await user.click(input);
    await user.click(await findListboxOption('Anduril'));
    await waitFor(() => expect(store.getState().app.selectedCompanyId).toBe('andurilindustries'));
    // A mouse pick leaves focus in the field, so this click is not a "first
    // focus" for MUI. Typing must still replace "Anduril", not append to it.
    expect(input).toHaveFocus();

    await user.click(input);
    await user.keyboard('sar');

    expect(input).toHaveValue('sar');
    await waitFor(() => expect(optionNames()).toEqual(rosterNamesContaining('sar')));
  });

  it('dispatches exactly setSelectedCompanyId + setSelectedATS when a filtered result is clicked', async () => {
    const user = userEvent.setup();
    const store = createTestStore();
    // Spied before render, so the component's `useAppDispatch` gets the spy.
    const dispatch = vi.spyOn(store, 'dispatch');
    render(
      <Provider store={store}>
        <CompanySelector />
      </Provider>
    );
    const input = companyInput();

    await user.click(input);
    await user.clear(input);
    await user.type(input, 'sar');
    await user.click(await findListboxOption('Saronic'));

    expect(dispatch).toHaveBeenCalledTimes(2);
    expect(dispatch).toHaveBeenNthCalledWith(1, setSelectedCompanyId('saronic'));
    expect(dispatch).toHaveBeenNthCalledWith(2, setSelectedATS(ATSConstants.BackendScraper));
    expect(store.getState().app.selectedCompanyId).toBe('saronic');
  });

  it('picks the top match with Enter after typing', async () => {
    const user = userEvent.setup();
    const store = renderSelector();
    const input = companyInput();

    await user.click(input);
    await user.clear(input);
    await user.type(input, 'saronic');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(store.getState().app.selectedCompanyId).toBe('saronic'));
    expect(input).toHaveValue('Saronic');
  });

  it('picks with the arrow keys and Enter', async () => {
    const user = userEvent.setup();
    const store = renderSelector();

    // Opening highlights the current pick (SpaceX), so one ArrowDown lands on
    // the company right after it in the alphabetical list.
    await user.click(companyInput());
    await screen.findByRole('listbox');
    await user.keyboard('{ArrowDown}{Enter}');

    const spacexIndex = PUBLIC_COMPANY_OPTIONS.findIndex((company) => company.id === 'spacex');
    const next = PUBLIC_COMPANY_OPTIONS[spacexIndex + 1];
    await waitFor(() => expect(store.getState().app.selectedCompanyId).toBe(next.id));
    expect(companyInput()).toHaveValue(next.name);
  });

  it('shows an empty field, with no warning and no blank row, for an id that matches no company', async () => {
    const user = userEvent.setup();
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      renderSelector('does-not-exist');

      expect(companyInput()).toHaveValue('');
      await user.click(companyInput());
      // The nameless stand-in value is never offered as a (blank) row.
      expect(optionNames()).toEqual(PUBLIC_COMPANY_OPTIONS.map((company) => company.name));
      // Nothing at all from React or MUI — including the "None of the options
      // match" warning older MUI printed for a value outside `options`.
      expect(warn).not.toHaveBeenCalled();
      expect(error).not.toHaveBeenCalled();
    } finally {
      warn.mockRestore();
      error.mockRestore();
    }
  });

  it('follows the store when the selection changes elsewhere', () => {
    const store = renderSelector();

    act(() => {
      store.dispatch(setSelectedCompanyId('andurilindustries'));
    });

    expect(companyInput()).toHaveValue('Anduril');
  });

  describe('URL synchronization', () => {
    beforeEach(() => {
      // Reset window.location and history before each test
      const url = 'http://localhost:5173/';
      Object.defineProperty(window, 'location', {
        value: new URL(url),
        writable: true,
        configurable: true,
      });

      vi.spyOn(window.history, 'pushState').mockImplementation(() => {});
      vi.clearAllMocks();
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('should dispatch setSelectedCompanyId action when company changes', async () => {
      const user = userEvent.setup();
      const testStore = renderSelector();

      // Open dropdown
      await user.click(companyInput());

      // Select a different company
      await user.click(await findListboxOption('Anthropic'));

      // Verify Redux state changed
      await waitFor(() => {
        expect(testStore.getState().app.selectedCompanyId).toBe('anthropic');
      });
    });
  });
});
