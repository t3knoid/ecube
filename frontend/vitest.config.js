import { fileURLToPath, URL } from 'node:url'
import { defineConfig, configDefaults } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    exclude: [...configDefaults.exclude, 'e2e/**'],
    root: fileURLToPath(new URL('./', import.meta.url)),
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      exclude: ['src/composables/useToast.js'],
      thresholds: {
        'src/stores/**/*.js': {
          lines: 80,
          functions: 75,
          branches: 70,
          statements: 80,
        },
        'src/composables/**/*.js': {
          lines: 80,
          functions: 50,
          branches: 60,
          statements: 80,
        },
      },
    },
  },
})
