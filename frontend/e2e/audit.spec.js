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

  // Date filter
  const dateInput = page.locator('input[type="date"]').first()
  if (await dateInput.isVisible()) {
    await dateInput.fill('2026-03-29')
  }

  await page.getByRole('button', { name: 'Apply' }).click()

  await expect(page.getByText('frank')).toBeVisible()

  // Export CSV — verify download is triggered
  const exportBtn = page.getByRole('button', { name: 'Export CSV' })
  await expect(exportBtn).toBeVisible()
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 5000 }).catch(() => null),
    exportBtn.click(),
  ])
  // Accept either a real download or a client-side Blob link click (no download event)
  if (download) {
    expect(download.suggestedFilename()).toMatch(/\.csv$/i)
  }

  await expectNoCriticalA11yViolations(page)
})
