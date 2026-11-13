import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// The dev server answers only localhost and raw IPs unless more host names are allowed:
// VITE_ALLOWED_HOSTS, comma separated (".example.net" allows every subdomain), from the
// environment, frontend/.env or the repo's .env. Empty or unset: Vite's default.
function allowedHosts(mode: string): string[] {
  const env = {
    ...loadEnv(mode, path.resolve(__dirname, '..'), ''),
    ...loadEnv(mode, __dirname, ''),
    ...process.env,
  }
  return (env.VITE_ALLOWED_HOSTS ?? '').split(',').map((h) => h.trim()).filter(Boolean)
}

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // dist/.vite/manifest.json: the bundle check (scripts/bundle-check.mjs) reads the chunk graph from it.
  build: {
    manifest: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: allowedHosts(mode),
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
  // Increase timeouts to accommodate longer backend processing (e.g., Telegram throttling)
  // Values are in milliseconds and are passed to http-proxy
  timeout: 180000,        // socket inactivity timeout (3 minutes)
  proxyTimeout: 180000,   // upstream response timeout (3 minutes)
      },
    },
  },
}))
