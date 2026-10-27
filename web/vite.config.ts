import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The UI talks to the brief service in services/api. In dev, /api is proxied
// to it; generation in agent mode can take a couple of minutes, hence the
// long timeouts.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: process.env.GRID_API_URL ?? 'http://localhost:8000',
        changeOrigin: true,
        timeout: 300_000,
        proxyTimeout: 300_000,
      },
    },
  },
})
