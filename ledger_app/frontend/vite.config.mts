import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => ({
  root: import.meta.dirname,
  base: mode === 'android' ? './' : '/',
  define: { 'import.meta.env.VITE_APP_TARGET': JSON.stringify(mode === 'android' ? 'android' : 'desktop') },
  plugins: [vue()],
  resolve: {
    alias: mode === 'android' ? {
      './App.vue': './MobileApp.vue',
      './style.css': './mobile-style.css',
    } : {},
  },
  build: {
    outDir: mode === 'android' ? 'dist-android' : '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
}))
