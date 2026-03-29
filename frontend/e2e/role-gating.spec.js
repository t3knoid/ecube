import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

async function commonRoutes(page) {
  await routeJson(page, '**/api/drives', [{ id: 1, current_state: 'AVAILABLE', device_identifier: '/dev/sdb', filesystem_type: 'ext4', capacity_bytes: 1000 }])
  await routeJson(page, '**/api/jobs**', [])
  await routeJson(page, '**/api/audit**', [])
}

test('processor cannot access admin views/actions', async ({ page }) => {
  await setupAuthenticatedPage(page, ['processor'])
  await commonRoutes(page)

  await page.goto('/users')
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('link', { name: 'Users' })).toHaveCount(0)

  await page.goto('/drives/1')
  await expect(page.getByRole('button', { name: 'Format' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Initialize' })).toBeDisabled()

  await expectNoCriticalA11yViolations(page)
})

test('auditor cannot run write actions', async ({ page }) => {
  await setupAuthenticatedPage(page, ['auditor'])
  await commonRoutes(page)
  await routeJson(page, '**/api/jobs/1', {
    id: 1,
    project_id: 'P',
    evidence_number: 'E',
    status: 'PENDING',
    copied_bytes: 0,
    total_bytes: 100,
  })
  await routeJson(page, '**/api/jobs/1/files', { files: [] })

  await page.goto('/jobs/1')
  await expect(page.getByRole('button', { name: 'Start' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Verify' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Generate Manifest' })).toBeDisabled()

  await expectNoCriticalA11yViolations(page)
})
