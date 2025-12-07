import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  // Set root to the frontend directory
  root: path.resolve(__dirname, 'src/frontend'),

  plugins: [react()],

  server: {
    port: 3000,
    open: false,  // Don't auto-open since vercel dev will report the URL
    // No need for proxy config - Vercel dev handles API routes
  },

  build: {
    // Output relative to the root (src/frontend)
    outDir: path.resolve(__dirname, 'src/frontend/dist'),
    sourcemap: true,
    // Empty the output directory before building
    emptyOutDir: true,
  },
});
