import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// src/server/server.py serves dist/ as it is: index.html for the three pages, the rest by its path.
// `npm run dev` serves the pages itself and hands /api (and what plugins serve themselves) to the
// Python server, which only answers its own origin: the proxy says it is that origin.
const SERVER = 'http://127.0.0.1:8787';
const toServer = { target: SERVER, changeOrigin: true, ws: true, headers: { origin: SERVER } };

// The plugins' page code (src/plugins.ts) lives in ../plugins/*/web, outside this package: it reaches
// the page's own modules as @ui/…, and React from here.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@ui': decodeURIComponent(new URL('./src', import.meta.url).pathname) },
    dedupe: ['react', 'react-dom'],
  },
  server: {
    proxy: { '/api': toServer, '/plugins': toServer },
    fs: { allow: ['.', '../plugins'] },
  },
});
