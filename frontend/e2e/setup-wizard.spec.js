import { test, expect } from '@playwright/test'
import { routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('setup wizard full step flow on uninitialized system', async ({ page }) => {
  const setupMocks = [
    ['**/api/setup/status', { initialized: false }],
    ['**/setup/status', { initialized: false }],
    ['**/api/setup/database/system-info', { in_docker: false, suggested_db_host: 'localhost', suggested_admin_username: 'postgres' }],
    ['**/setup/database/system-info', { in_docker: false, suggested_db_host: 'localhost', suggested_admin_username: 'postgres' }],
    ['**/api/setup/database/provision-status', { provisioned: false }],
    ['**/setup/database/provision-status', { provisioned: false }],
    ['**/api/setup/database/test-connection', { ok: true }],
    ['**/setup/database/test-connection', { ok: true }],
    ['**/api/setup/database/provision', { ok: true }],
    ['**/setup/database/provision', { ok: true }],
    ['**/api/setup/initialize', { ok: true }],
    ['**/setup/initialize', { ok: true }],
    ['**/api/telemetry/ui-navigation', { ok: true }],
    ['**/telemetry/ui-navigation', { ok: true }],
  ]
  for (const [pattern, body] of setupMocks) {
    await routeJson(page, pattern, body)
  }

  await page.goto('/setup')

  await page.getByLabel('DB Admin User').fill('postgres')
  await page.getByLabel('DB Admin Password').fill('testpassword')
  await page.getByRole('button', { name: /connect to database|test database connection/i }).click()
  await expect(page.getByText('Database connection succeeded.')).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click()

  await page.getByLabel('Application DB Password').fill('dbapppassword')
  await page.getByRole('button', { name: 'Provision Database' }).click()
  await expect(page.getByText('Database provisioned successfully.')).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click()

  await page.getByLabel('Password').fill('AdminPass123!')
  await page.getByRole('button', { name: 'Create Admin User' }).click()
  await expect(page.getByText('Admin user created successfully. Continue to the next step.')).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click()

  await expect(page.getByRole('button', { name: 'Go to Login' })).toBeEnabled()

  await expectNoCriticalA11yViolations(page)
})
