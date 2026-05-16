import { describe, it, expect } from 'vitest';
import { extractErrorMessage } from '../../lib/errors';

describe('extractErrorMessage', () => {
  describe('Error instances', () => {
    it('returns the message from an Error', () => {
      expect(extractErrorMessage(new Error('boom'))).toBe('boom');
    });

    it('returns fallback when Error.message is empty', () => {
      expect(extractErrorMessage(new Error(''))).toBe('Unknown error');
    });

    it('returns the message from a subclass of Error', () => {
      class NetworkError extends Error {}
      expect(extractErrorMessage(new NetworkError('offline'))).toBe('offline');
    });
  });

  describe('string errors', () => {
    it('returns the string as-is', () => {
      expect(extractErrorMessage('something went wrong')).toBe('something went wrong');
    });

    it('returns an empty string as-is (does NOT fall back)', () => {
      expect(extractErrorMessage('')).toBe('');
    });
  });

  describe('RTK Query { data } shape', () => {
    it('returns data when it is a plain string', () => {
      expect(extractErrorMessage({ data: 'bad request' })).toBe('bad request');
    });

    it('returns data.detail when present', () => {
      expect(extractErrorMessage({ data: { detail: 'company not found' } })).toBe(
        'company not found'
      );
    });

    it('returns data.message when detail is absent', () => {
      expect(extractErrorMessage({ data: { message: 'server exploded' } })).toBe(
        'server exploded'
      );
    });

    it('prefers data.detail over data.message when both present', () => {
      expect(
        extractErrorMessage({ data: { detail: 'detail wins', message: 'ignored' } })
      ).toBe('detail wins');
    });

    it('falls through to fallback when data is an object with neither detail nor message', () => {
      expect(extractErrorMessage({ data: { code: 500 } })).toBe('Unknown error');
    });

    it('falls through when data.detail is an empty string', () => {
      expect(extractErrorMessage({ data: { detail: '', message: 'backup' } })).toBe('backup');
    });

    it('falls through when data.detail is not a string (uses data.message)', () => {
      // The non-string detail branch must not short-circuit; message should win.
      expect(extractErrorMessage({ data: { detail: 123, message: 'x' } })).toBe('x');
    });

    it('falls through when data is null', () => {
      expect(extractErrorMessage({ data: null })).toBe('Unknown error');
    });
  });

  describe('generic { message } shape', () => {
    it('returns message from a plain object', () => {
      expect(extractErrorMessage({ message: 'failed' })).toBe('failed');
    });

    it('falls through when message is not a string', () => {
      expect(extractErrorMessage({ message: 123 })).toBe('Unknown error');
    });
  });

  describe('nullish and unknown shapes', () => {
    it('returns fallback for null', () => {
      expect(extractErrorMessage(null)).toBe('Unknown error');
    });

    it('returns fallback for undefined', () => {
      expect(extractErrorMessage(undefined)).toBe('Unknown error');
    });

    it('returns fallback for numbers', () => {
      expect(extractErrorMessage(42)).toBe('Unknown error');
    });

    it('returns fallback for booleans', () => {
      expect(extractErrorMessage(true)).toBe('Unknown error');
    });

    it('returns fallback for empty objects', () => {
      expect(extractErrorMessage({})).toBe('Unknown error');
    });
  });

  describe('RTK Query { error } shape (CUSTOM_ERROR / FETCH_ERROR)', () => {
    // The runtime guards in ``adminApi.ts`` throw via ``transformResponse``;
    // RTK Query then wraps the thrown ``Error`` into
    // ``{ status: 'CUSTOM_ERROR', error: '...message...' }``. Without
    // reading ``err.error``, the consumer (AdminUsersPage) saw the generic
    // fallback and never the actionable "Invalid /api/admin/users response:
    // missing users[]" guard message.
    it('returns CUSTOM_ERROR message from err.error string', () => {
      expect(
        extractErrorMessage({
          status: 'CUSTOM_ERROR',
          error: 'Invalid /api/admin/users response: missing users[]',
        })
      ).toBe('Invalid /api/admin/users response: missing users[]');
    });

    it('returns FETCH_ERROR message from err.error string', () => {
      expect(
        extractErrorMessage({
          status: 'FETCH_ERROR',
          error: 'TypeError: Failed to fetch',
        })
      ).toBe('TypeError: Failed to fetch');
    });

    it('returns nested err.error.message when err.error is an object', () => {
      // Mirrors SerializedError shape; some RTK Query middlewares nest the
      // error object rather than flattening to a string.
      expect(
        extractErrorMessage({
          status: 'CUSTOM_ERROR',
          error: { message: 'guard tripped', name: 'Error' },
        })
      ).toBe('guard tripped');
    });

    it('prefers data.detail over err.error when both present', () => {
      // The priority order keeps existing call sites' behavior identical.
      expect(
        extractErrorMessage({
          data: { detail: 'detail wins' },
          error: 'error loses',
        })
      ).toBe('detail wins');
    });

    it('falls through when err.error is an empty string', () => {
      expect(
        extractErrorMessage({ status: 'CUSTOM_ERROR', error: '' })
      ).toBe('Unknown error');
    });

    it('falls through when err.error is not a string and has no message', () => {
      expect(
        extractErrorMessage({ status: 'CUSTOM_ERROR', error: { code: 500 } })
      ).toBe('Unknown error');
    });
  });

  describe('custom fallback', () => {
    it('uses the custom fallback when no branch matches', () => {
      expect(extractErrorMessage(null, 'Failed to save changes')).toBe(
        'Failed to save changes'
      );
    });

    it('uses the custom fallback for an empty Error message', () => {
      expect(extractErrorMessage(new Error(''), 'Request failed')).toBe('Request failed');
    });

    it('does not use the fallback when a valid message is available', () => {
      expect(extractErrorMessage(new Error('real'), 'never used')).toBe('real');
    });
  });
});
