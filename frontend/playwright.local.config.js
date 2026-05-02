import baseConfig from './playwright.config.js'

export default {
  ...baseConfig,
  testDir: '/home/frank/ecube/frontend/e2e',
  use: {
    ...baseConfig.use,
    baseURL: 'http://127.0.0.1:4173',
  },
  webServer: undefined,
}