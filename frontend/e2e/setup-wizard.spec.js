import { test, expect } from '@playwright/test'
import { routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('setup wizard full step flow on uninitialized system', async ({ page }) => {
  await routeJson(page, '**/api/setup/status', { initialized: false })
  await routeJson(page, '**/api/setup/database/system-info', { in_docker: false, suggested_db_host: 'localhost' })
  await routeJson(page, '**/api/setup/database/provision-status', { provisioned: false })
  await routeJson(page, '**/api/setup/database/test-connection', { ok: true })
  await routeJson(page, '**/api/setup/database/provision', { ok: true })
  await routeJson(page, '**/api/setup/initialize', { ok: true })

  await page.goto('/setup')

  await page.getByLabel('DB Admin Password').fill('testpassword')
  await page.getByRole('button', { name: 'Test Database Connection' }).click()
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
