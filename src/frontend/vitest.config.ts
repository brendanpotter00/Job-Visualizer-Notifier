import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    // Default Vitest timeout is 5s, which is too tight for userEvent-heavy
    // tests (e.g. EnabledCompaniesSection) that routinely run 4-5s and flake
    // out under parallel CPU contention. 15s is comfortably above the real
    // runtime for every test in the suite while still catching genuine hangs.
    testTimeout: 15000,
    // Worker threads start faster than the default child processes; across the
    // 230 jsdom files that cut ~15% off the suite's wall time. Measured
    // `deps.optimizer` too — it made the suite slower, so it stays off.
    pool: 'threads',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/dist/**',
      ],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
    },
  },
});
