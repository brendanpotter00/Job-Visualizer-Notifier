import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 3000,
    open: true,
    proxy: {
      // Proxy to local FastAPI backend
      '/api/jobs': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      '/api/greenhouse': {
        target: 'https://boards-api.greenhouse.io',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/greenhouse/, ''),
        secure: false,
      },
      '/api/lever': {
        target: 'https://api.lever.co',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/lever/, ''),
        secure: false,
      },
      '/api/ashby': {
        target: 'https://api.ashbyhq.com',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/ashby/, ''),
        secure: false,
      },
      '/api/users': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      // Workday proxy removed - use `vercel dev` for local Workday testing
      // The serverless function (api/workday.ts) handles dynamic routing for multiple Workday tenants
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
