import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  root: import.meta.dirname,
  base: '/static/vue/',
  plugins: [vue()],
  build: {
    outDir: '../static/vue',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
