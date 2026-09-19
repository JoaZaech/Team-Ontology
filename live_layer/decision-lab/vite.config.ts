import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Production is served by viseca_mock.py. Keep the same-origin API contract
// during Vite development by proxying it to the local mock service.
// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/mock': 'http://127.0.0.1:8082',
      '/v1': 'http://127.0.0.1:8082',
    },
  },
})
