import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

async function mockCoreApis(page) {
  await routeJson(page, '**/api/drives', [{ id: 1, current_state: 'AVAILABLE', device_identifier: '/dev/sdb', filesystem_type: 'ext4', capacity_bytes: 1000 }])
  await routeJson(page, '**/api/jobs**', [{ id: 55, project_id: 'PRJ', status: 'RUNNING', copied_bytes: 20, total_bytes: 100 }])
  await routeJson(page, '**/api/audit**', [{ id: 1, user: 'frank', action: 'LOGIN', timestamp: '2026-03-29T00:00:00Z', details: {} }])
  await routeJson(page, '**/api/jobs/55', { id: 55, project_id: 'PRJ', evidence_number: 'EV', status: 'RUNNING', copied_bytes: 20, total_bytes: 100 })
  await routeJson(page, '**/api/jobs/55/files', { files: [] })
  await routeJson(page, '**/api/introspection/jobs/55/debug', { files: [] })
}

test('theme switch changes css variables', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await mockCoreApis(page)

  await page.goto('/')

  const before = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim())
  await page.locator('.theme-select').selectOption('dark')
  const after = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim())

  expect(before).not.toBe(after)
  await expectNoCriticalA11yViolations(page)
})

test('visual regression snapshots for key screens in default and dark themes', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await mockCoreApis(page)

  const shots = [
    { path: '/login', name: 'login' },
    { path: '/', name: 'dashboard' },
    { path: '/drives', name: 'drives' },
    { path: '/jobs/55', name: 'job-detail' },
    { path: '/audit', name: 'audit' },
  ]

  for (const shot of shots) {
    await page.goto(shot.path)
    await expect(page).toHaveScreenshot(`${shot.name}-default.png`)
  }

  await page.goto('/')
  await page.locator('.theme-select').selectOption('dark')

  for (const shot of shots) {
    await page.goto(shot.path)
    await expect(page).toHaveScreenshot(`${shot.name}-dark.png`)
  }
})
