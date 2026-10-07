import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// The LOCAL-ONLY admin bypass (VITE_DEV_AUTH_BYPASS=1) is decided once at
// module evaluation, so each case re-imports config/auth after stubbing env.
// `import.meta.env.DEV` is what `vite build` replaces with `false`; stubbing it
// to false here is the production-build case.
describe('AUTH_CONFIG.devAdminBypassEnabled (local dev admin bypass)', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.resetModules();
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    warnSpy.mockRestore();
  });

  it('is on with VITE_DEV_AUTH_BYPASS=1 under the dev server, and warns loudly', async () => {
    vi.stubEnv('DEV', true);
    vi.stubEnv('VITE_DEV_AUTH_BYPASS', '1');
    vi.stubEnv('VITE_AUTH_BYPASS', '');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.devAdminBypassEnabled).toBe(true);
    expect(AUTH_CONFIG.bypassEnabled).toBe(false);
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('VITE_DEV_AUTH_BYPASS is ON'));
  });

  it('is off in a production build (DEV=false) even with the flag set', async () => {
    vi.stubEnv('DEV', false);
    vi.stubEnv('VITE_DEV_AUTH_BYPASS', '1');
    vi.stubEnv('VITE_AUTH_BYPASS', '');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.devAdminBypassEnabled).toBe(false);
    expect(warnSpy).not.toHaveBeenCalledWith(expect.stringContaining('VITE_DEV_AUTH_BYPASS'));
  });

  it('is off when the flag is unset or not exactly "1"', async () => {
    vi.stubEnv('DEV', true);
    vi.stubEnv('VITE_AUTH_BYPASS', '');
    vi.stubEnv('VITE_DEV_AUTH_BYPASS', '');
    expect((await import('../../config/auth')).AUTH_CONFIG.devAdminBypassEnabled).toBe(false);

    vi.resetModules();
    vi.stubEnv('VITE_DEV_AUTH_BYPASS', 'true');
    expect((await import('../../config/auth')).AUTH_CONFIG.devAdminBypassEnabled).toBe(false);
  });

  it('throws at module evaluation when both bypass flags are set', async () => {
    vi.stubEnv('DEV', true);
    vi.stubEnv('VITE_DEV_AUTH_BYPASS', '1');
    vi.stubEnv('VITE_AUTH_BYPASS', 'true');
    await expect(import('../../config/auth')).rejects.toThrow(
      /VITE_AUTH_BYPASS and VITE_DEV_AUTH_BYPASS are both set/
    );
  });
});
