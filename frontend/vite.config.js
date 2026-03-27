import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
/** Replaces %BASE_URL% in index.html with the resolved Vite base path. */
function baseUrlHtmlPlugin() {
  let resolvedBase = '/'
  return {
    name: 'base-url-html',
    configResolved(config) {
      resolvedBase = config.base
    },
    transformIndexHtml(html) {
      return html.replaceAll('%BASE_URL%', resolvedBase)
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [
    baseUrlHtmlPlugin(),
    vue(),
    ...(mode === 'development' ? [vueDevTools()] : []),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api(\/|$)/, '/'),
      },
    },
  },
}))
