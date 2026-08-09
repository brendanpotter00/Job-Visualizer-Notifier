import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('CUSTOM_COMPANIES_CONFIG', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('isEnabled is true only for the exact string "true"', async () => {
    vi.stubEnv('VITE_CUSTOM_COMPANIES_ENABLED', 'true');
    const { CUSTOM_COMPANIES_CONFIG } = await import('../../config/customCompanies');
    expect(CUSTOM_COMPANIES_CONFIG.isEnabled).toBe(true);
  });

  it('defaults to OFF when the var is unset', async () => {
    // Explicitly delete rather than relying on the var being absent: Vite
    // loads `src/frontend/.env.local` in test mode too, so a developer who
    // enables the flag locally would otherwise fail this test (and only this
    // test) on their machine while CI stayed green.
    vi.stubEnv('VITE_CUSTOM_COMPANIES_ENABLED', undefined);
    const { CUSTOM_COMPANIES_CONFIG } = await import('../../config/customCompanies');
    expect(CUSTOM_COMPANIES_CONFIG.isEnabled).toBe(false);
  });

  it.each(['', 'false', 'TRUE', 'True', '1', 'yes', 'on'])(
    'stays OFF for the truthy-looking value %o',
    async (value) => {
      // Strict equality is deliberate: a half-configured env must fail closed.
      vi.stubEnv('VITE_CUSTOM_COMPANIES_ENABLED', value);
      const { CUSTOM_COMPANIES_CONFIG } = await import('../../config/customCompanies');
      expect(CUSTOM_COMPANIES_CONFIG.isEnabled).toBe(false);
    }
  );
});
