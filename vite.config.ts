import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ['react', 'react-dom'],
  },
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:41900', changeOrigin: true },
      '/ws':  { target: 'ws://127.0.0.1:41900',  ws: true },
    },
  },
  build: {
    outDir: './builds/static',
    emptyOutDir: true,
    sourcemap: true,
    minify: false,
  },
})
