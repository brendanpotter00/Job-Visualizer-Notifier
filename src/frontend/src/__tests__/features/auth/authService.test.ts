import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchCurrentUser, updateCurrentUser } from '../../../features/auth/authService';

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
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify(mockUser), { status: 200 })
      );

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

      await expect(fetchCurrentUser('token')).rejects.toThrow(
        /missing isAdmin field/
      );
    });

    it('rejects a 2xx body whose isAdmin is not a boolean', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(
          JSON.stringify({ ...mockUser, isAdmin: 'true' }),
          { status: 200 }
        )
      );

      await expect(fetchCurrentUser('token')).rejects.toThrow(
        /missing isAdmin field/
      );
    });
  });

  describe('updateCurrentUser', () => {
    it('sends PUT request with body and Bearer token', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify(mockUser), { status: 200 })
      );

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
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ ...mockUser, displayName: null }), { status: 200 })
      );

      await updateCurrentUser('token', { displayName: null });

      const body = JSON.parse(fetchSpy.mock.calls[0][1]!.body as string);
      expect(body.displayName).toBeNull();
    });

    it('throws on 404 response', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response('Not Found', { status: 404 })
      );

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
  });
});
