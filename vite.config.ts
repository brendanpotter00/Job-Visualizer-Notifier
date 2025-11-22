import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    open: true,
    proxy: {
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
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
