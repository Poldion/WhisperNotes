import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = process.env.WHISPERNOTES_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  base: '/dashboard/',
  plugins: [react()],
  server: {
    proxy: {
      '/api': backend,
      '/v1': backend,
      '/health': backend,
    },
  },
})
