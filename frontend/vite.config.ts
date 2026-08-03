import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    allowedHosts: ['stove-creole-oblivious.ngrok-free.dev'],
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:8000',
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true
      },
      '/mock-lab-health': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
        rewrite: () => '/health'
      },
      '/mock-lab-api': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/mock-lab-api/, '/api')
      }
    }
  }
})
