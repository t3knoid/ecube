import baseConfig from './playwright.config.js'

export default {
  ...baseConfig,
  testDir: './e2e',
  use: {
    ...baseConfig.use,
    baseURL: 'http://127.0.0.1:4173',
  },
  webServer: undefined,
}