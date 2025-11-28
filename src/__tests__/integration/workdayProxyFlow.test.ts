/**
 * Integration tests for Workday proxy flow
 *
 * Tests the complete client → server encoding/decoding flow
 */

import { describe, it, expect } from 'vitest';
import { encodeBase64url, decodeBase64url } from '@shared/base64url';

describe('Workday Proxy Flow Integration', () => {
  describe('Client-to-Server encoding flow', () => {
    it('should encode NVIDIA domain on client and decode on server correctly', () => {
      // 1. Simulate client encoding
      const domain = 'nvidia.wd5.myworkdayjobs.com';
      const encodedOnClient = encodeBase64url(domain);

      // 2. Verify encoded format is URL-safe
      expect(encodedOnClient).toMatch(/^[A-Za-z0-9_-]+$/);
      expect(encodedOnClient).not.toContain('+');
      expect(encodedOnClient).not.toContain('/');
      expect(encodedOnClient).not.toContain('=');

      // 3. Simulate server decoding
      const decodedOnServer = decodeBase64url(encodedOnClient);

      // 4. Verify round-trip
      expect(decodedOnServer).toBe(domain);
    });

    it('should handle multiple Workday domain formats', () => {
      const workdayDomains = [
        'nvidia.wd5.myworkdayjobs.com',
        'acme.wd5.myworkdayjobs.com',
        'test-company.wd5.myworkdayjobs.com',
        'company-123.wd5.myworkdayjobs.com',
        'my-company-name.wd5.myworkdayjobs.com',
      ];

      for (const domain of workdayDomains) {
        // Client encodes
        const encoded = encodeBase64url(domain);

        // Verify URL-safe
        expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);

        // Server decodes
        const decoded = decodeBase64url(encoded);

        // Verify round-trip
        expect(decoded).toBe(domain);
      }
    });
  });

  describe('URL construction', () => {
    it('should create valid API URL with encoded domain', () => {
      const domain = 'nvidia.wd5.myworkdayjobs.com';
      const tenantSlug = 'nvidia';
      const careerSiteSlug = 'NVIDIAExternalCareerSite';

      // Encode domain
      const encodedDomain = encodeBase64url(domain);

      // Construct API URL (as done in workdayClient.ts)
      const apiBase = '/api/workday';
      const jobsUrl = `${apiBase}/${encodedDomain}/wday/cxs/${tenantSlug}/${careerSiteSlug}/jobs`;

      // Verify URL structure
      expect(jobsUrl).toContain('/api/workday/');
      expect(jobsUrl).toContain('/wday/cxs/');
      expect(jobsUrl).toContain(encodedDomain);

      // Verify we can extract and decode domain from URL
      const urlParts = jobsUrl.split('/');
      const encodedFromUrl = urlParts[3]; // /api/workday/{encoded}/...
      const decodedFromUrl = decodeBase64url(encodedFromUrl);

      expect(decodedFromUrl).toBe(domain);
    });

    it('should create valid target URL on server side', () => {
      const domain = 'nvidia.wd5.myworkdayjobs.com';
      const encodedDomain = encodeBase64url(domain);

      // Simulate server receiving encoded domain
      const decodedDomain = decodeBase64url(encodedDomain);

      // Construct target URL (as done in api/workday.ts)
      const remainingPath = 'wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs';
      const targetUrl = `https://${decodedDomain}/${remainingPath}`;

      // Verify target URL
      expect(targetUrl).toBe(`https://${domain}/${remainingPath}`);
      expect(targetUrl).toContain('nvidia.wd5.myworkdayjobs.com');
      expect(targetUrl).not.toContain('undefined');
      expect(targetUrl).not.toMatch(/[\x00-\x1F\x7F-\x9F]/); // No control characters
    });
  });

  describe('Error handling in proxy flow', () => {
    it('should fail gracefully with invalid encoded domain', () => {
      // Simulate server receiving corrupted base64url
      const invalidEncoded = 'invalid+/=chars';

      expect(() => decodeBase64url(invalidEncoded)).toThrow();
    });

    it('should fail gracefully with empty encoded domain', () => {
      expect(() => decodeBase64url('')).toThrow();
    });

    it('should prevent encoding of invalid domains', () => {
      const invalidDomains = ['invalid..domain', '-invalid.com', 'invalid-.com'];

      for (const domain of invalidDomains) {
        expect(() => encodeBase64url(domain)).toThrow();
      }
    });
  });

  describe('Real-world scenarios', () => {
    it('should handle actual NVIDIA production domain', () => {
      // This is the actual domain used in production
      const productionDomain = 'nvidia.wd5.myworkdayjobs.com';
      const productionTenant = 'nvidia';
      const productionCareerSite = 'NVIDIAExternalCareerSite';

      // Simulate full flow
      const encoded = encodeBase64url(productionDomain);
      const apiUrl = `/api/workday/${encoded}/wday/cxs/${productionTenant}/${productionCareerSite}/jobs`;

      // Extract encoded domain from URL
      const extractedEncoded = apiUrl.split('/')[3];
      const decoded = decodeBase64url(extractedEncoded);

      // Build target URL
      const targetUrl = `https://${decoded}/wday/cxs/${productionTenant}/${productionCareerSite}/jobs`;

      // Verify final URL is correct
      expect(targetUrl).toBe(
        'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs'
      );

      // Verify no corruption
      expect(targetUrl).not.toMatch(/[\x00-\x1F\x7F-\x9F]/);
      expect(targetUrl).not.toContain('undefined');
      expect(targetUrl).not.toContain('null');
    });

    it('should maintain encoding consistency across multiple calls', () => {
      const domain = 'nvidia.wd5.myworkdayjobs.com';

      // Encode multiple times
      const encoded1 = encodeBase64url(domain);
      const encoded2 = encodeBase64url(domain);
      const encoded3 = encodeBase64url(domain);

      // All should be identical
      expect(encoded1).toBe(encoded2);
      expect(encoded2).toBe(encoded3);

      // All should decode to same domain
      expect(decodeBase64url(encoded1)).toBe(domain);
      expect(decodeBase64url(encoded2)).toBe(domain);
      expect(decodeBase64url(encoded3)).toBe(domain);
    });
  });
});
