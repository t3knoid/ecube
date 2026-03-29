import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('audit filters and export csv', async ({ page }) => {
  await setupAuthenticatedPage(page, ['auditor'])

  await page.route('**/api/audit**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 1,
          timestamp: '2026-03-29T10:00:00Z',
          user: 'frank',
          action: 'LOGIN',
          job_id: null,
          client_ip: '127.0.0.1',
          details: { message: 'ok' },
        },
      ]),
    })
  })

  await page.goto('/audit')
  await page.getByPlaceholder('Filter by user').fill('frank')
  await page.getByPlaceholder('Filter by action').fill('LOGIN')
  await page.getByRole('button', { name: 'Apply' }).click()

  await expect(page.getByText('frank')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Export CSV' })).toBeVisible()

  await expectNoCriticalA11yViolations(page)
})
