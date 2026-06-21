import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AsyncMultiSelectAutocomplete } from '../../../../components/shared/filters/AsyncMultiSelectAutocomplete';

const { searchMock } = vi.hoisted(() => ({ searchMock: vi.fn() }));

vi.mock('../../../../features/preferences/preferencesApi', () => ({
  useSearchLocationsQuery: (...args: unknown[]) => searchMock(...args),
}));

beforeEach(() => searchMock.mockReset());

const noop = () => {};

describe('AsyncMultiSelectAutocomplete failure surfacing', () => {
  it('surfaces a failed location search instead of an empty void', () => {
    searchMock.mockReturnValue({
      data: undefined,
      isFetching: false,
      isError: true,
      error: { data: { detail: 'Failed to search locations' } },
    });
    render(
      <AsyncMultiSelectAutocomplete label="Locations" value={[]} onAdd={noop} onRemove={noop} />
    );
    // The error is shown as the field's helper text (visible even when closed).
    expect(screen.getByText('Failed to search locations')).toBeInTheDocument();
  });

  it('falls back to a generic message when the error has no detail', () => {
    searchMock.mockReturnValue({
      data: undefined,
      isFetching: false,
      isError: true,
      error: undefined,
    });
    render(
      <AsyncMultiSelectAutocomplete label="Locations" value={[]} onAdd={noop} onRemove={noop} />
    );
    expect(screen.getByText('Location search failed')).toBeInTheDocument();
  });

  it('shows no error helper text on a healthy (non-error) query', () => {
    searchMock.mockReturnValue({
      data: [],
      isFetching: false,
      isError: false,
      error: undefined,
    });
    render(
      <AsyncMultiSelectAutocomplete label="Locations" value={[]} onAdd={noop} onRemove={noop} />
    );
    expect(screen.queryByText(/failed/i)).not.toBeInTheDocument();
  });
});
