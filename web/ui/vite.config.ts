import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// web/server.py serves dist/ as it is: index.html for the three pages, the rest by its path.
// `npm run dev` serves the pages itself and hands /api (and VS Code's tunnel) to the Python
// server, which only answers its own origin: the proxy says it is that origin.
const SERVER = 'http://127.0.0.1:8787';
const toServer = { target: SERVER, changeOrigin: true, ws: true, headers: { origin: SERVER } };

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': toServer, '/vscode': toServer } },
});
