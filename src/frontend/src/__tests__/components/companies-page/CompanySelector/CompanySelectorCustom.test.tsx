import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';

/**
 * T6 — the ask itself: a user's own boards are selectable from the Company
 * Hiring Trends dropdown, under their own heading, under the name the USER gave
 * them.
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
import { createTestStore } from '../../../../test/testUtils';
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

async function renderSelector(boards: UserCompany[]) {
  const store = createTestStore();
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
    // Production shape: the board was discovered as "cisco" and renamed. The
    // wire `displayName` is already COALESCE(user_display_name, display_name),
    // so the rename must show up with nothing merged client-side.
    await renderSelector([board('u-jw8iz8sqvy', 'Raindrop YC')]);

    await user.click(screen.getByRole('combobox'));

    // The badge is part of the option's accessible name, not a separate node —
    // it renders inside the row so a screen reader reads "Raindrop YC Custom".
    expect(await screen.findByRole('option', { name: /Raindrop YC/ })).toBeInTheDocument();
    expect(screen.getByText('Custom')).toBeInTheDocument();
    // The curated roster is still all there, and carries no badge.
    expect(screen.getByRole('option', { name: 'SpaceX' })).toBeInTheDocument();
    // No group headings at all any more — one list, ordered by name.
    expect(screen.queryByText('Your companies')).not.toBeInTheDocument();
    expect(screen.queryByText('Tracked by us')).not.toBeInTheDocument();
  });

  it('sorts a custom board into the curated list by NAME, not into a block at the end', async () => {
    const user = userEvent.setup();
    // "Cisco" must land among the Cs. The whole point of the change is that a
    // company is where its name says it is.
    await renderSelector([board('u-abc123', 'Cisco')]);

    await user.click(screen.getByRole('combobox'));
    await screen.findByRole('option', { name: /Cisco/ });

    const names = screen
      .getAllByRole('option')
      .map((option) => option.textContent?.replace(/Custom$/, '').trim() ?? '');
    const sorted = [...names].sort((a, b) => a.localeCompare(b));
    expect(names).toEqual(sorted);
    // ...and it is genuinely interleaved, not first or last.
    const index = names.indexOf('Cisco');
    expect(index).toBeGreaterThan(0);
    expect(index).toBeLessThan(names.length - 1);
  });

  it('selects the board, so the trend page loads it like any other company', async () => {
    const user = userEvent.setup();
    const store = await renderSelector([board('u-abc123', 'Cisco')]);

    await user.click(screen.getByRole('combobox'));
    // Regex, not an exact string: the row now renders the badge inside it, so
    // the option's accessible name is "Cisco Custom".
    await user.click(await screen.findByRole('option', { name: /^Cisco/ }));

    await waitFor(() => expect(store.getState().app.selectedCompanyId).toBe('u-abc123'));
  });

  it('shows no badge at all when the viewer owns nothing — the list as before', async () => {
    const user = userEvent.setup();
    await renderSelector([]);

    await user.click(screen.getByRole('combobox'));

    await screen.findByRole('option', { name: 'SpaceX' });
    expect(screen.queryByText('Custom')).not.toBeInTheDocument();
    expect(screen.queryByText('Your companies')).not.toBeInTheDocument();
    expect(screen.queryByText('Tracked by us')).not.toBeInTheDocument();
  });

  it('shows nothing custom with the flag off, even with boards cached', async () => {
    const user = userEvent.setup();
    const store = createTestStore();
    await store.dispatch(
      userCompaniesApi.util.upsertQueryData('getUserCompanies', undefined, {
        companies: [board('u-abc123', 'Cisco')],
      })
    );
    flagState.isEnabled = false;
    render(
      <Provider store={store}>
        <CompanySelector />
      </Provider>
    );

    await user.click(screen.getByRole('combobox'));

    await screen.findByRole('option', { name: 'SpaceX' });
    expect(screen.queryByText('Your companies')).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Cisco' })).not.toBeInTheDocument();
  });
});
