import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { GiveFeedbackBox } from '../../../pages/VoteFeaturesPage/GiveFeedbackBox';
import { registerTokenGetter } from '../../../features/features/getTokenOrNull';

// RTK Query's fetchBaseQuery builds `new Request('/api/feedback')` with a
// relative URL; undici's Request rejects that under jsdom. Resolve relative
// URLs against a test origin (same shim as the *Api.test.ts files).
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (typeof input === 'string' && input.startsWith('/')) {
      super(`http://localhost${input}`, init);
    } else {
      super(input, init);
    }
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function authHeaderFromCall(call: [unknown, unknown]): string | null {
  const [input, init] = call;
  if (input instanceof Request) return input.headers.get('Authorization');
  const headers = (init as RequestInit | undefined)?.headers;
  if (headers instanceof Headers) return headers.get('Authorization');
  if (headers && typeof headers === 'object') {
    const rec = headers as Record<string, string>;
    const key = Object.keys(rec).find((k) => k.toLowerCase() === 'authorization');
    return key ? rec[key] : null;
  }
  return null;
}

describe('GiveFeedbackBox', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    registerTokenGetter(null);
  });

  afterEach(() => {
    vi.clearAllMocks();
    registerTokenGetter(null);
  });

  it('renders the heading, email link, and a disabled Send button initially', () => {
    renderWithProviders(<GiveFeedbackBox />);
    expect(screen.getByRole('heading', { name: /give feedback/i })).toBeInTheDocument();
    const emailLink = screen.getByRole('link', { name: 'brendanpotter00@gmail.com' });
    expect(emailLink).toHaveAttribute('href', 'mailto:brendanpotter00@gmail.com');
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
  });

  it('keeps Send disabled for whitespace-only input and enables it for real text', async () => {
    const user = userEvent.setup();
    renderWithProviders(<GiveFeedbackBox />);
    const textbox = screen.getByRole('textbox');
    const sendButton = screen.getByRole('button', { name: /send/i });

    await user.type(textbox, '   ');
    expect(sendButton).toBeDisabled();

    await user.type(textbox, 'real feedback');
    expect(sendButton).toBeEnabled();
  });

  it('submits successfully, shows a confirmation, and clears the textbox', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'fb1' }, 201));
    const user = userEvent.setup();
    renderWithProviders(<GiveFeedbackBox />);

    const textbox = screen.getByRole('textbox') as HTMLTextAreaElement;
    await user.type(textbox, 'great app');
    await user.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findByText(/thanks/i)).toBeInTheDocument();
    expect(textbox.value).toBe('');

    // Anonymous submission carries no Authorization header.
    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(authHeaderFromCall(call)).toBeNull();
  });

  it('shows an error and preserves the text when submission fails', async () => {
    // The backend error detail ("boom") is surfaced via extractErrorMessage;
    // when the body has no detail the component falls back to a generic message.
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'boom' }, 500));
    const user = userEvent.setup();
    renderWithProviders(<GiveFeedbackBox />);

    const textbox = screen.getByRole('textbox') as HTMLTextAreaElement;
    await user.type(textbox, 'will fail');
    await user.click(screen.getByRole('button', { name: /send/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/boom/i);
    expect(textbox.value).toBe('will fail');
  });

  it('falls back to a generic error message when the body has no detail', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 500));
    const user = userEvent.setup();
    renderWithProviders(<GiveFeedbackBox />);

    await user.type(screen.getByRole('textbox'), 'will fail');
    await user.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findByText(/failed to send feedback/i)).toBeInTheDocument();
  });

  it('attaches a Bearer token when the user is authenticated', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'fb1' }, 201));
    registerTokenGetter(async () => 'tok-authed');
    const user = userEvent.setup();
    renderWithProviders(<GiveFeedbackBox />);

    await user.type(screen.getByRole('textbox'), 'from signed-in user');
    await user.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(authHeaderFromCall(call)).toBe('Bearer tok-authed');
  });
});
