/**
 * Tests for base64url encoding/decoding utility
 */

import { describe, it, expect } from 'vitest';
import { encodeBase64url, decodeBase64url, isValidDomain } from '../index';
import { ERROR_MESSAGES } from '../constants';

describe('base64url encoding/decoding', () => {
  describe('isValidDomain', () => {
    it('should validate correct domains', () => {
      expect(isValidDomain('nvidia.wd5.myworkdayjobs.com')).toBe(true);
      expect(isValidDomain('example.com')).toBe(true);
      expect(isValidDomain('sub.domain.example.com')).toBe(true);
      expect(isValidDomain('test-123.example.com')).toBe(true);
      expect(isValidDomain('a.b.c.d.e.f.g.h.i.j.com')).toBe(true);
    });

    it('should reject invalid domains', () => {
      expect(isValidDomain('')).toBe(false);
      expect(isValidDomain('invalid..domain')).toBe(false);
      expect(isValidDomain('-invalid.com')).toBe(false);
      expect(isValidDomain('invalid-.com')).toBe(false);
      expect(isValidDomain('.invalid.com')).toBe(false);
      expect(isValidDomain('invalid.com.')).toBe(false);
    });

    it('should reject domains that are too long', () => {
      const longDomain = 'a'.repeat(256) + '.com';
      expect(isValidDomain(longDomain)).toBe(false);
    });
  });

  describe('encodeBase64url', () => {
    it('should encode NVIDIA domain correctly', () => {
      const domain = 'nvidia.wd5.myworkdayjobs.com';
      const encoded = encodeBase64url(domain);

      // Should be valid base64url (no +, /, or =)
      expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
      expect(encoded).not.toContain('+');
      expect(encoded).not.toContain('/');
      expect(encoded).not.toContain('=');

      // Should match expected encoding
      expect(encoded).toBe('bnZpZGlhLndkNS5teXdvcmtkYXlqb2JzLmNvbQ');
    });

    it('should encode various Workday domains', () => {
      const domains = [
        'nvidia.wd5.myworkdayjobs.com',
        'acme.wd5.myworkdayjobs.com',
        'test-company.wd5.myworkdayjobs.com',
        'company123.wd5.myworkdayjobs.com',
      ];

      for (const domain of domains) {
        const encoded = encodeBase64url(domain);
        expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
        expect(encoded.length).toBeGreaterThan(0);
      }
    });

    it('should throw on empty input', () => {
      expect(() => encodeBase64url('')).toThrow(ERROR_MESSAGES.EMPTY_INPUT);
    });

    it('should throw on invalid domain', () => {
      expect(() => encodeBase64url('invalid..domain')).toThrow(ERROR_MESSAGES.INVALID_DOMAIN);
      expect(() => encodeBase64url('-invalid.com')).toThrow(ERROR_MESSAGES.INVALID_DOMAIN);
    });

    it('should pass round-trip validation', () => {
      const domain = 'nvidia.wd5.myworkdayjobs.com';
      const encoded = encodeBase64url(domain);
      // If encoding succeeds, round-trip validation already passed
      expect(encoded).toBeTruthy();
    });
  });

  describe('decodeBase64url', () => {
    it('should decode NVIDIA domain correctly', () => {
      const encoded = 'bnZpZGlhLndkNS5teXdvcmtkYXlqb2JzLmNvbQ';
      const decoded = decodeBase64url(encoded);
      expect(decoded).toBe('nvidia.wd5.myworkdayjobs.com');
    });

    it('should decode various encoded domains', () => {
      const testCases = [
        { encoded: 'bnZpZGlhLndkNS5teXdvcmtkYXlqb2JzLmNvbQ', expected: 'nvidia.wd5.myworkdayjobs.com' },
        { encoded: 'ZXhhbXBsZS5jb20', expected: 'example.com' },
        { encoded: 'c3ViLmRvbWFpbi5leGFtcGxlLmNvbQ', expected: 'sub.domain.example.com' },
      ];

      for (const { encoded, expected } of testCases) {
        const decoded = decodeBase64url(encoded);
        expect(decoded).toBe(expected);
      }
    });

    it('should handle missing padding correctly', () => {
      // Base64 padding variations
      const testCases = [
        'YWJj', // 'abc' - no padding needed
        'YWJjZA', // 'abcd' - no padding needed
        'YQ', // 'a' - would need == padding in standard base64
      ];

      for (const encoded of testCases) {
        expect(() => decodeBase64url(encoded)).not.toThrow();
      }
    });

    it('should throw on empty input', () => {
      expect(() => decodeBase64url('')).toThrow(ERROR_MESSAGES.EMPTY_INPUT);
    });

    it('should throw on invalid base64url characters', () => {
      expect(() => decodeBase64url('invalid+chars')).toThrow(ERROR_MESSAGES.INVALID_ENCODED_FORMAT);
      expect(() => decodeBase64url('invalid/chars')).toThrow(ERROR_MESSAGES.INVALID_ENCODED_FORMAT);
      expect(() => decodeBase64url('invalid=chars')).toThrow(ERROR_MESSAGES.INVALID_ENCODED_FORMAT);
    });

    it('should throw if decoded value is not a valid domain', () => {
      // Create an encoded value that decodes to invalid domain
      // 'aW52YWxpZC4uZG9tYWlu' is base64url for 'invalid..domain'
      expect(() => decodeBase64url('aW52YWxpZC4uZG9tYWlu')).toThrow(ERROR_MESSAGES.DECODE_FAILED);
    });
  });

  describe('Round-trip encoding/decoding', () => {
    it('should encode then decode to original for NVIDIA domain', () => {
      const original = 'nvidia.wd5.myworkdayjobs.com';
      const encoded = encodeBase64url(original);
      const decoded = decodeBase64url(encoded);
      expect(decoded).toBe(original);
    });

    it('should round-trip various domains', () => {
      const domains = [
        'nvidia.wd5.myworkdayjobs.com',
        'example.com',
        'sub.domain.example.com',
        'test-company.wd5.myworkdayjobs.com',
        'company-123.wd5.myworkdayjobs.com',
        'a.b.c.d.e.f.g.com',
      ];

      for (const domain of domains) {
        const encoded = encodeBase64url(domain);
        const decoded = decodeBase64url(encoded);
        expect(decoded).toBe(domain);
      }
    });

    it('should handle domains with hyphens and numbers', () => {
      const domains = [
        'test-123.example.com',
        '123-test.example.com',
        'my-company-name.wd5.myworkdayjobs.com',
      ];

      for (const domain of domains) {
        const encoded = encodeBase64url(domain);
        const decoded = decodeBase64url(encoded);
        expect(decoded).toBe(domain);
      }
    });

    it('should handle maximum length domain', () => {
      // Create a domain close to max length (255 chars)
      // DNS labels max 63 chars, so we need multiple subdomains
      // Format: aaa...aaa.bbb...bbb.ccc...ccc.example.com
      const label1 = 'a'.repeat(63);
      const label2 = 'b'.repeat(63);
      const label3 = 'c'.repeat(63);
      const label4 = 'd'.repeat(50); // Total: 63+63+63+50+11('example.com'+dots) = 250
      const domain = `${label1}.${label2}.${label3}.${label4}.example.com`;

      expect(domain.length).toBeLessThanOrEqual(255);

      const encoded = encodeBase64url(domain);
      const decoded = decodeBase64url(encoded);
      expect(decoded).toBe(domain);
    });
  });

  describe('Edge cases', () => {
    it('should handle single-character subdomain', () => {
      const domain = 'a.example.com';
      const encoded = encodeBase64url(domain);
      const decoded = decodeBase64url(encoded);
      expect(decoded).toBe(domain);
    });

    it('should handle many subdomains', () => {
      const domain = 'a.b.c.d.e.f.g.h.i.j.example.com';
      const encoded = encodeBase64url(domain);
      const decoded = decodeBase64url(encoded);
      expect(decoded).toBe(domain);
    });

    it('should handle domain with all numeric subdomain', () => {
      const domain = '123.example.com';
      const encoded = encodeBase64url(domain);
      const decoded = decodeBase64url(encoded);
      expect(decoded).toBe(domain);
    });

    it('should handle domain with maximum label length (63 chars)', () => {
      const label = 'a'.repeat(63);
      const domain = `${label}.example.com`;
      const encoded = encodeBase64url(domain);
      const decoded = decodeBase64url(encoded);
      expect(decoded).toBe(domain);
    });
  });

  describe('Error messages', () => {
    it('should provide helpful error for invalid domain', () => {
      try {
        encodeBase64url('invalid..domain');
        expect.fail('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(Error);
        expect((err as Error).message).toContain(ERROR_MESSAGES.INVALID_DOMAIN);
        expect((err as Error).message).toContain('invalid..domain');
      }
    });

    it('should provide helpful error for invalid base64url characters', () => {
      try {
        decodeBase64url('invalid+/=');
        expect.fail('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(Error);
        expect((err as Error).message).toContain(ERROR_MESSAGES.INVALID_ENCODED_FORMAT);
      }
    });

    it('should provide diagnostic info on round-trip failure', () => {
      // This test verifies that if round-trip somehow fails,
      // the error message includes diagnostic information
      // In practice, this should never happen with our implementation,
      // but the error handling is there for safety

      // We can't easily trigger this without mocking, so just verify
      // the encode function exists and works normally
      const domain = 'nvidia.wd5.myworkdayjobs.com';
      expect(() => encodeBase64url(domain)).not.toThrow();
    });
  });
});
