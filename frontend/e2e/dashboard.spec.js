import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('dashboard loads with summary cards and counts', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await routeJson(page, '**/api/drives', [
    { id: 1, current_state: 'EMPTY' },
    { id: 2, current_state: 'AVAILABLE' },
    { id: 3, current_state: 'IN_USE' },
  ])
  await routeJson(page, '**/api/jobs**', [
    { id: 11, project_id: 'P-001', status: 'RUNNING', copied_bytes: 50, total_bytes: 100 },
    { id: 12, project_id: 'P-002', status: 'COMPLETED', copied_bytes: 100, total_bytes: 100 },
  ])

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect(page.getByText('Drive Summary')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Active Jobs' })).toBeVisible()
  await expect(page.getByText('P-001')).toBeVisible()

  await expectNoCriticalA11yViolations(page)
})

test('dashboard shows preparing label for startup-phase active jobs', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await routeJson(page, '**/api/drives', [])
  await routeJson(page, '**/api/jobs**', [
    {
      id: 21,
      project_id: 'P-021',
      status: 'RUNNING',
      copied_bytes: 0,
      total_bytes: 0,
      file_count: 0,
      files_succeeded: 0,
      files_failed: 0,
    },
  ])

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Active Jobs' })).toBeVisible()
  await expect(page.getByText('P-021')).toBeVisible()
  await expect(page.locator('.dashboard-progress-cell').getByText('Preparing...', { exact: true }).first()).toBeVisible()

  await expectNoCriticalA11yViolations(page)
})
