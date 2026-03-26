import { test, expect } from '@playwright/test'

// See here how to get started:
// https://playwright.dev/docs/intro
test('visits the app root url', async ({ page }) => {
  // Stub the setup-status API so the router treats the system as initialized
  await page.route('**/api/setup/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ initialized: true }),
    }),
  )

  await page.goto('/')
  // Unauthenticated users are redirected to the login page
  await expect(page.locator('h1')).toHaveText('ECUBE')
})
