import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// The fixtures live at the repo root so the agent backend and the UI share them.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    fs: { allow: [path.resolve(import.meta.dirname, '..')] },
  },
})
