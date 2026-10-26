import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the Vite server proxies API and WebSocket traffic to the
// FastAPI backend on port 8080. In production the backend serves this build.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8080',
        ws: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8080',
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // noVNC 1.7 uses top-level await; ES2022 is supported by all current browsers
    target: 'es2022',
    chunkSizeWarningLimit: 900,
  },
  optimizeDeps: {
    esbuildOptions: { target: 'es2022' },
  },
})
