// vite.config.js
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5002,  // Your frontend port
    proxy: {
      '/api': {
        target: 'http://localhost:5000',  // Your backend
        changeOrigin: true,
        // 10-minute timeout for 3D generation requests (LHM can take 5-10 min)
        timeout: 600000,
        proxyTimeout: 600000,
      },
      '/outputs': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      }
    }
  }
});