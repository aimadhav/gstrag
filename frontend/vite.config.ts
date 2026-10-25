import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig(({ command, isPreview }) => ({
  plugins: [react()],
  base: command === 'build' || isPreview ? '/app/' : '/',
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: {
      '/api': {
        target: process.env.GST_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/api(?=\/)/, ''),
      },
    },
  },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], css: false },
}));
