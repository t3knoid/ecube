import { test, expect } from '@playwright/test'

// Helper: create a fake JWT with the given payload (valid for e2e route testing)
function makeToken(payload) {
  const encode = (obj) => btoa(JSON.stringify(obj))
  return `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode(payload)}.${encode('sig')}`
}

// Stub /api/setup/status to return the given initialized value
function stubSetupStatus(page, initialized) {
  return page.route('**/api/setup/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ initialized }),
    }),
  )
}

// Inject a valid auth token into sessionStorage before navigation
function injectAuthToken(page, roles = []) {
  const exp = Math.floor(Date.now() / 1000) + 3600
  const jwt = makeToken({ sub: 'frank', roles, groups: [], exp })
  return page.addInitScript((token) => {
    sessionStorage.setItem('ecube_token', token)
  }, jwt)
}

// See here how to get started:
// https://playwright.dev/docs/intro
test('visits the app root url', async ({ page }) => {
  // Stub the setup-status API so the router treats the system as initialized
  await stubSetupStatus(page, true)

  await page.goto('/')
  // Unauthenticated users are redirected to the login page
  await expect(page.locator('h1')).toHaveText('ECUBE')
})

test('redirects to /setup when system is not initialized', async ({ page }) => {
  await stubSetupStatus(page, false)

  await page.goto('/')
  await page.waitForURL('**/setup')
  await expect(page).toHaveURL(/\/setup$/)
})

test('redirects away from /audit when user lacks required role', async ({ page }) => {
  await stubSetupStatus(page, true)
  // Stub system-health so AppFooter polling doesn't error
  await page.route('**/api/introspection/system-health', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  )
  await page.route('**/api/introspection/version', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"version":"test"}' }),
  )
  // Processor role cannot access /audit (requires admin, manager, or auditor)
  await injectAuthToken(page, ['processor'])

  await page.goto('/audit')
  // Should be redirected to the dashboard
  await page.waitForURL('**/')
  await expect(page).toHaveURL(/^\/$|\/$/);
})

test('redirects away from /users when user is not admin', async ({ page }) => {
  await stubSetupStatus(page, true)
  await page.route('**/api/introspection/system-health', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  )
  await page.route('**/api/introspection/version', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"version":"test"}' }),
  )
  // Manager role cannot access /users (requires admin)
  await injectAuthToken(page, ['manager'])

  await page.goto('/users')
  await page.waitForURL('**/')
  await expect(page).toHaveURL(/^\/$|\/$/);
})
