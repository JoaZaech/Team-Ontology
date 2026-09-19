import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Fully static app: all data lives in src/fixtures.ts, no server to proxy to.
// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
})
