import { describe, it, expect, afterEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';

/**
 * T6 — the ask itself: a user's own boards are selectable from the Company
 * Hiring Trends company search, in the one alphabetical list, badged, under the
 * name the USER gave them.
 */
const { flagState } = vi.hoisted(() => ({ flagState: { isEnabled: true } }));
vi.mock('../../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: {
    get isEnabled() {
      return flagState.isEnabled;
    },
    isDiscoveryProgressEnabled: false,
  },
}));

import { CompanySelector } from '../../../../components/companies-page/CompanySelector/CompanySelector';
import { createTestStore, findListboxOption } from '../../../../test/testUtils';
import { userCompaniesApi } from '../../../../features/userCompanies/userCompaniesApi';
import type { UserCompany } from '../../../../features/userCompanies/userCompaniesApi';

function board(id: string, displayName: string): UserCompany {
  return {
    id,
    displayName,
    ats: 'discovered',
    boardToken: `https://${id}.example.com/careers`,
    sourceId: `custom:${id}`,
    healthState: 'healthy',
    openJobCount: 5,
    lastSuccessAt: null,
    trackingStartedAt: null,
  };
}

async function renderSelector(boards: UserCompany[], selectedCompanyId?: string) {
  const store = createTestStore(
    selectedCompanyId
      ? { app: { selectedCompanyId, selectedATS: 'backend-scraper', isInitialized: true } }
      : {}
  );
  if (boards.length > 0) {
    await store.dispatch(
      userCompaniesApi.util.upsertQueryData('getUserCompanies', undefined, { companies: boards })
    );
  }
  render(
    <Provider store={store}>
      <CompanySelector />
    </Provider>
  );
  return store;
}

afterEach(() => {
  flagState.isEnabled = true;
});

describe('CompanySelector — the viewer’s own boards', () => {
  it('lists them inline, badged, with the name the user chose', async () => {
    const user = userEvent.setup();
    // Production shape: the board was discovered as "acmeboards" and renamed. The
    // wire `displayName` is already COALESCE(user_display_name, display_name),
    // so the rename must show up with nothing merged client-side.
    await renderSelector([board('u-jw8iz8sqvy', 'Raindrop YC')]);

    await user.click(screen.getByRole('combobox'));

    // The badge is part of the option's accessible name, not a separate node —
    // it renders inside the row so a screen reader reads "Raindrop YC Custom".
    expect(await findListboxOption('Raindrop YC')).toHaveAccessibleName('Raindrop YC Custom');
    expect(screen.getByText('Custom')).toBeInTheDocument();
    // The curated roster is still all there, and carries no badge.
    expect(await findListboxOption('SpaceX')).toHaveAccessibleName('SpaceX');
    // No group headings at all any more — one list, ordered by name.
    expect(screen.queryByText('Your companies')).not.toBeInTheDocument();
    expect(screen.queryByText('Tracked by us')).not.toBeInTheDocument();
  });

  it('sorts a custom board into the curated list by NAME, not into a block at the end', async () => {
    const user = userEvent.setup();
    // "Meridian Labs" must land among the Ms. The whole point of the change is
    // that a company sits where its name says it does.
    //
    // A DELIBERATELY FICTIONAL name, and it has to stay fictional. This first
    // used "Cisco", which broke the moment Cisco was added to the curated
    // roster — the dropdown then held two options matching /Cisco/ and the
    // query became ambiguous. Any real company name is a landmine here, because
    // the roster is exactly the thing that grows.
    await renderSelector([board('u-abc123', 'Meridian Labs')]);

    await user.click(screen.getByRole('combobox'));
    await findListboxOption('Meridian Labs');

    const names = screen
      .getAllByRole('option')
      .map((option) => option.textContent?.replace(/Custom$/, '').trim() ?? '');
    const sorted = [...names].sort((a, b) => a.localeCompare(b));
    expect(names).toEqual(sorted);
    // ...and it is genuinely interleaved, not first or last.
    const index = names.indexOf('Meridian Labs');
    expect(index).toBeGreaterThan(0);
    expect(index).toBeLessThan(names.length - 1);
  });

  it('selects the board, so the trend page loads it like any other company', async () => {
    const user = userEvent.setup();
    const store = await renderSelector([board('u-abc123', 'Acme Boards')]);

    await user.click(screen.getByRole('combobox'));
    // By visible label: the row renders the badge inside it, so the option's
    // accessible name is "Acme Boards Custom". (Fixture name from main, which
    // genericised it away from a real company.)
    await user.click(await findListboxOption('Acme Boards'));

    await waitFor(() => expect(store.getState().app.selectedCompanyId).toBe('u-abc123'));
  });

  it('shows just the name in the field when a board is selected; the badge is for the list', async () => {
    await renderSelector([board('u-jw8iz8sqvy', 'Raindrop YC')], 'u-jw8iz8sqvy');

    expect(screen.getByRole('combobox', { name: 'Company' })).toHaveValue('Raindrop YC');
    // Closed: no row is rendered, so no badge either.
    expect(screen.queryByText('Custom')).not.toBeInTheDocument();
  });

  it('finds a board by typing part of its name, badge and all', async () => {
    const user = userEvent.setup();
    const store = await renderSelector([board('u-abc123', 'Meridian Labs')]);
    const input = screen.getByRole('combobox', { name: 'Company' });

    await user.click(input);
    await user.clear(input);
    // Fictional on purpose, for the reason the sorting test above gives. Mixed
    // case and mid-word, so it only matches as a case-insensitive substring.
    await user.type(input, 'IDIAN la');

    const listbox = await screen.findByRole('listbox');
    const [only, ...rest] = within(listbox).getAllByRole('option');
    expect(rest).toEqual([]);
    expect(only).toHaveAccessibleName('Meridian Labs Custom');

    await user.click(only);
    await waitFor(() => expect(store.getState().app.selectedCompanyId).toBe('u-abc123'));
    // The badge never leaks into the field's text.
    expect(input).toHaveValue('Meridian Labs');
  });

  it('waits quietly for a selected board whose list has not landed yet', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      // `?company=u-abc123` is selected before GET /api/users/companies answers.
      const store = await renderSelector([], 'u-abc123');
      const input = screen.getByRole('combobox', { name: 'Company' });

      // No name to show yet, rather than a guessed one.
      expect(input).toHaveValue('');

      await act(async () => {
        await store.dispatch(
          userCompaniesApi.util.upsertQueryData('getUserCompanies', undefined, {
            companies: [board('u-abc123', 'Acme Boards')],
          })
        );
      });

      // `waitFor`, not a bare expect: RTK's auto-batch enhancer tells subscribers
      // about RTK Query actions on the next animation frame, after `act` returns.
      await waitFor(() => expect(input).toHaveValue('Acme Boards'));
      expect(warn).not.toHaveBeenCalled();
      expect(error).not.toHaveBeenCalled();
    } finally {
      warn.mockRestore();
      error.mockRestore();
    }
  });

  it('shows no badge at all when the viewer owns nothing — the list as before', async () => {
    const user = userEvent.setup();
    await renderSelector([]);

    await user.click(screen.getByRole('combobox'));

    await findListboxOption('SpaceX');
    expect(screen.queryByText('Custom')).not.toBeInTheDocument();
    expect(screen.queryByText('Your companies')).not.toBeInTheDocument();
    expect(screen.queryByText('Tracked by us')).not.toBeInTheDocument();
  });

  it('shows nothing custom with the flag off, even with boards cached', async () => {
    const user = userEvent.setup();
    const store = createTestStore();
    await store.dispatch(
      userCompaniesApi.util.upsertQueryData('getUserCompanies', undefined, {
        companies: [board('u-abc123', 'Acme Boards')],
      })
    );
    flagState.isEnabled = false;
    render(
      <Provider store={store}>
        <CompanySelector />
      </Provider>
    );

    await user.click(screen.getByRole('combobox'));

    await findListboxOption('SpaceX');
    expect(screen.queryByText('Your companies')).not.toBeInTheDocument();
    // By text, not by exact accessible name: a badged row is named "Acme Boards
    // Custom", so `queryByRole('option', { name: 'Acme Boards' })` could never match.
    expect(screen.queryByText('Acme Boards')).not.toBeInTheDocument();
  });
});
