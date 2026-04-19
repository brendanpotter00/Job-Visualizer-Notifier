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
