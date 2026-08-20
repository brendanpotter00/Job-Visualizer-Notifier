import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { jobsApi } from '../../../features/jobs/jobsApi';
import {
  SubcategoryRevealProvider,
  useSubcategoryRevealEnabled,
} from '../../../features/settings/subcategoryReveal';

function makeStore() {
  return configureStore({
    reducer: { [jobsApi.reducerPath]: jobsApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(jobsApi.middleware),
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** Renders the boolean so a test can read it off the DOM. */
function Probe({ label = 'probe' }: { label?: string }) {
  const enabled = useSubcategoryRevealEnabled();
  return <span data-testid={label}>{String(enabled)}</span>;
}

describe('SubcategoryRevealProvider', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(jsonResponse({ sweSubcategoriesEnabled: false }));
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('publishes true when the cached flag is on', async () => {
    const store = makeStore();
    await store.dispatch(
      jobsApi.util.upsertQueryData('getPublicSettings', undefined, {
        sweSubcategoriesEnabled: true,
      })
    );

    render(
      <Provider store={store}>
        <SubcategoryRevealProvider>
          <Probe />
        </SubcategoryRevealProvider>
      </Provider>
    );

    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('true'));
  });

  it('publishes false when the cached flag is off', async () => {
    const store = makeStore();
    await store.dispatch(
      jobsApi.util.upsertQueryData('getPublicSettings', undefined, {
        sweSubcategoriesEnabled: false,
      })
    );

    render(
      <Provider store={store}>
        <SubcategoryRevealProvider>
          <Probe />
        </SubcategoryRevealProvider>
      </Provider>
    );

    expect(screen.getByTestId('probe')).toHaveTextContent('false');
  });

  it('yields false and does NOT throw when the endpoint 404s', async () => {
    // The Vercel-ahead-of-Railway window. An unfinished feature must stay
    // hidden, and nothing here may surface an error state — the filter bar has
    // nowhere to render one.
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Not Found' }, 404));
    const store = makeStore();

    render(
      <Provider store={store}>
        <SubcategoryRevealProvider>
          <Probe />
        </SubcategoryRevealProvider>
      </Provider>
    );

    // False immediately (loading) and still false once the 404 has settled.
    expect(screen.getByTestId('probe')).toHaveTextContent('false');
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByTestId('probe')).toHaveTextContent('false');
  });

  it('issues EXACTLY ONE fetch no matter how many consumers read it', async () => {
    // The subscription-count guarantee that justifies the context at all.
    // JobChipsSection renders once per card in a virtualized list; the hook
    // form would mint one RTK Query subscription per card.
    fetchMock.mockResolvedValue(jsonResponse({ sweSubcategoriesEnabled: true }));
    const store = makeStore();

    render(
      <Provider store={store}>
        <SubcategoryRevealProvider>
          {Array.from({ length: 25 }, (_, i) => (
            <Probe key={i} label={`probe-${i}`} />
          ))}
        </SubcategoryRevealProvider>
      </Provider>
    );

    await waitFor(() => expect(screen.getByTestId('probe-0')).toHaveTextContent('true'));

    const settingsCalls = fetchMock.mock.calls.filter((call) =>
      String(call[0]).includes('/api/jobs/settings')
    );
    expect(settingsCalls).toHaveLength(1);
    expect(screen.getByTestId('probe-24')).toHaveTextContent('true');
  });

  it('yields false outside a provider — the default is closed', () => {
    render(<Probe />);
    expect(screen.getByTestId('probe')).toHaveTextContent('false');
  });
});
