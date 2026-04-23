import { test, expect } from '@playwright/test'
import { injectAuthToken, setupPublicPage } from './helpers/app.js'

// See here how to get started:
// https://playwright.dev/docs/intro
test('visits the app root url', async ({ page }) => {
  await setupPublicPage(page, { initialized: true })

  await page.goto('/')
  // Unauthenticated users are redirected to the login page
  await expect(page.locator('h1')).toHaveText('ECUBE')
})

test('redirects to /setup when system is not initialized', async ({ page }) => {
  await setupPublicPage(page, { initialized: false })

  await page.goto('/')
  await page.waitForURL('**/setup')
  await expect(page).toHaveURL(/\/setup$/)
})

test('redirects away from /audit when user lacks required role', async ({ page }) => {
  await setupPublicPage(page, { initialized: true })
  // Processor role cannot access /audit (requires admin, manager, or auditor)
  await injectAuthToken(page, ['processor'])

  await page.goto('/audit')
  // Should be redirected to the dashboard
  await page.waitForURL('**/')
  expect(new URL(page.url()).pathname).toBe('/')
})

test('redirects away from /users when user is not admin', async ({ page }) => {
  await setupPublicPage(page, { initialized: true })
  // Manager role cannot access /users (requires admin)
  await injectAuthToken(page, ['manager'])

  await page.goto('/users')
  await page.waitForURL('**/')
  expect(new URL(page.url()).pathname).toBe('/')
})

test('admin users page exposes a single editable users table', async ({ page }) => {
  await setupPublicPage(page, { initialized: true })

  // Users screen data endpoints
  await page.route('**/api/users', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ users: [{ username: 'frank', roles: ['admin'] }] }),
    }),
  )
  await page.route('**/api/admin/os-users', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ users: [{ username: 'alba', uid: 1001, gid: 1001, home: '/home/alba', shell: '/bin/bash', groups: ['ecube-processors'] }] }),
    }),
  )
  await page.route('**/api/users/alba/roles', (route) => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ username: 'alba', roles: ['manager'] }),
      })
    }
    return route.continue()
  })

  await injectAuthToken(page, ['admin'])
  await page.goto('/users')

  // Tabs are removed; editing is consolidated into one users table.
  await expect(page.locator('.tabs .btn')).toHaveCount(0)
  await expect(page.getByRole('columnheader', { name: 'Roles' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Reset Password' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Save' })).toHaveCount(0)

  const userRow = page.getByRole('row').filter({ hasText: 'alba' })
  const saveButton = userRow.getByRole('button', { name: 'Save' })
  const managerCheckbox = userRow.getByRole('checkbox', { name: /^manager$/i })

  await expect(saveButton).toBeVisible()
  await expect(saveButton).toBeDisabled()
  await managerCheckbox.check()
  await expect(saveButton).toBeEnabled()
  await saveButton.click()
  await expect(saveButton).toBeDisabled()
})
