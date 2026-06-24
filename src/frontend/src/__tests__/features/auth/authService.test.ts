import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  fetchCurrentUser,
  recordVisit,
  updateCurrentUser,
} from '../../../features/auth/authService';

const mockUser = {
  id: 'abc123',
  providerSubject: 'auth0|test',
  email: 'test@example.com',
  displayName: 'Test User',
  givenName: 'Test',
  familyName: 'User',
  pictureUrl: 'https://example.com/photo.jpg',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  isAdmin: false,
};

describe('authService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('fetchCurrentUser', () => {
    it('sends GET request with Bearer token', async () => {
      const fetchSpy = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValue(new Response(JSON.stringify(mockUser), { status: 200 }));

      await fetchCurrentUser('my-token');

      expect(fetchSpy).toHaveBeenCalledWith('/api/users', {
        headers: {
          Authorization: 'Bearer my-token',
          Accept: 'application/json',
        },
      });
    });

    it('returns parsed user data', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify(mockUser), { status: 200 })
      );

      const user = await fetchCurrentUser('token');
      expect(user).toEqual(mockUser);
    });

    it('throws on 401 response', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response('Unauthorized', { status: 401 })
      );

      await expect(fetchCurrentUser('bad-token')).rejects.toThrow('Failed to fetch user (401)');
    });

    it('throws on 500 response', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response('Internal Server Error', { status: 500 })
      );

      await expect(fetchCurrentUser('token')).rejects.toThrow('Failed to fetch user (500)');
    });

    it('rejects a 2xx body that is missing the isAdmin field', async () => {
      // Regression guard symmetric to AdminUsersListResponse's runtime
      // guard. The backend hardening makes isAdmin a required Pydantic
      // field — but a CDN error page or proxy misroute could still
      // return a 2xx JSON body without it. If that response were cast
      // straight to ``User`` (the prior behavior), AdminRoute's
      // ``!user.isAdmin`` check would silently demote the admin. The
      // parseUserResponse guard must reject this body at the fetch
      // boundary so the error surfaces in useCurrentUser instead.
      const bodyMissingIsAdmin = {
        id: 'abc123',
        providerSubject: 'auth0|test',
        email: 'test@example.com',
        displayName: null,
        givenName: null,
        familyName: null,
        pictureUrl: null,
        createdAt: '2026-01-01T00:00:00Z',
        updatedAt: '2026-01-01T00:00:00Z',
      };
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify(bodyMissingIsAdmin), { status: 200 })
      );

      await expect(fetchCurrentUser('token')).rejects.toThrow(/missing isAdmin field/);
    });

    it('rejects a 2xx body whose isAdmin is not a boolean', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ ...mockUser, isAdmin: 'true' }), { status: 200 })
      );

      await expect(fetchCurrentUser('token')).rejects.toThrow(/missing isAdmin field/);
    });

    it('extracts a readable message when the error body has a nested error object', async () => {
      // Audit pass-3 finding: ``extractErrorDetail`` did
      // ``b.detail || b.message || b.error`` and returned the value
      // directly. When ``error`` was an object (e.g. an upstream returns
      // ``{ "error": { "code": "BACKEND_DOWN", "message": "pool exhausted" } }``),
      // the object was returned as-is and ``new Error(object)`` coerced
      // it to the string ``"[object Object]"`` — completely opaque to
      // the on-call admin.
      //
      // Fix: every field is filtered by ``typeof === 'string'``, and the
      // top-level ``error`` field's nested ``.message`` is read if present.
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: 'BACKEND_DOWN', message: 'pool exhausted' },
          }),
          { status: 500 }
        )
      );

      await expect(fetchCurrentUser('token')).rejects.toThrow(/pool exhausted/);
    });

    it('falls back through non-string detail/message to the generic message', async () => {
      // A ``detail`` object should NOT be passed straight to ``new
      // Error(...)``. The guard requires ``typeof === 'string'`` at
      // every step, so a non-string detail falls through to the
      // generic fallback rather than rendering as ``[object Object]``.
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ detail: { nested: 'oops' } }), {
          status: 500,
        })
      );

      const error = await fetchCurrentUser('token').catch((e) => e);
      // Must not be the coerced object stringification.
      expect((error as Error).message).not.toBe('[object Object]');
      // Falls back to the synthesized status message.
      expect((error as Error).message).toMatch(/Failed to fetch user|500/);
    });
  });

  describe('updateCurrentUser', () => {
    it('sends PUT request with body and Bearer token', async () => {
      const fetchSpy = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValue(new Response(JSON.stringify(mockUser), { status: 200 }));

      await updateCurrentUser('my-token', { displayName: 'New Name' });

      expect(fetchSpy).toHaveBeenCalledWith('/api/users', {
        method: 'PUT',
        headers: {
          Authorization: 'Bearer my-token',
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ displayName: 'New Name' }),
      });
    });

    it('returns updated user data', async () => {
      const updated = { ...mockUser, displayName: 'New Name' };
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify(updated), { status: 200 })
      );

      const user = await updateCurrentUser('token', { displayName: 'New Name' });
      expect(user.displayName).toBe('New Name');
    });

    it('sends null displayName to clear it', async () => {
      const fetchSpy = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValue(
          new Response(JSON.stringify({ ...mockUser, displayName: null }), { status: 200 })
        );

      await updateCurrentUser('token', { displayName: null });

      const body = JSON.parse(fetchSpy.mock.calls[0][1]!.body as string);
      expect(body.displayName).toBeNull();
    });

    it('throws on 404 response', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('Not Found', { status: 404 }));

      await expect(updateCurrentUser('token', { displayName: 'X' })).rejects.toThrow(
        'Failed to update user (404)'
      );
    });

    it('throws on 500 response', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response('Server Error', { status: 500 })
      );

      await expect(updateCurrentUser('token', { displayName: 'X' })).rejects.toThrow(
        'Failed to update user (500)'
      );
    });

    it('rejects a 2xx PUT body that is missing the isAdmin field', async () => {
      // Audit pass-3 finding: parseUserResponse runs at both the GET and
      // PUT boundaries (``updateCurrentUser`` returns ``User`` and calls
      // ``parseUserResponse(await response.json())`` per pass 2). The
      // missing-isAdmin guard was only tested via the GET path; a
      // future regression that bypassed parsing on the PUT path would
      // silently demote the admin every time they updated their
      // display name.
      const bodyMissingIsAdmin = {
        id: 'abc123',
        providerSubject: 'auth0|test',
        email: 'test@example.com',
        displayName: 'New Name',
        givenName: null,
        familyName: null,
        pictureUrl: null,
        createdAt: '2026-01-01T00:00:00Z',
        updatedAt: '2026-01-02T00:00:00Z',
      };
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify(bodyMissingIsAdmin), { status: 200 })
      );

      await expect(updateCurrentUser('token', { displayName: 'New Name' })).rejects.toThrow(
        /missing isAdmin field/
      );
    });

    it('rejects a 2xx PUT body whose isAdmin is not a boolean', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ ...mockUser, isAdmin: 1 }), { status: 200 })
      );

      await expect(updateCurrentUser('token', { displayName: 'X' })).rejects.toThrow(
        /missing isAdmin field/
      );
    });
  });

  describe('recordVisit', () => {
    it('sends a POST to /api/users/visit with Bearer token and no body', async () => {
      const fetchSpy = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValue(new Response(null, { status: 204 }));

      await recordVisit('my-token');

      expect(fetchSpy).toHaveBeenCalledWith('/api/users/visit', {
        method: 'POST',
        headers: {
          Authorization: 'Bearer my-token',
          Accept: 'application/json',
        },
      });
    });

    it('resolves on 204 No Content', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));

      await expect(recordVisit('token')).resolves.toBeUndefined();
    });

    it('throws on a non-2xx response so the caller can log-and-swallow', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response('Server Error', { status: 500 })
      );

      await expect(recordVisit('token')).rejects.toThrow('Failed to record visit (500)');
    });
  });
});
