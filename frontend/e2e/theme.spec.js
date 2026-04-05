import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

async function mockCoreApis(page) {
  await routeJson(page, '**/api/drives', [{ id: 1, current_state: 'AVAILABLE', device_identifier: '/dev/sdb', filesystem_type: 'ext4', capacity_bytes: 1000 }])
  await routeJson(page, '**/api/mounts', [])
  await routeJson(page, '**/api/users', { users: [{ username: 'frank', roles: ['admin'] }] })
  await routeJson(page, '**/api/admin/os-users', { users: [{ uid: 1001, username: 'frank', groups: ['ecube-admin'] }] })
  await routeJson(page, '**/api/jobs**', [{ id: 55, project_id: 'PRJ', status: 'RUNNING', copied_bytes: 20, total_bytes: 100 }])
  await routeJson(page, '**/api/audit**', [{ id: 1, user: 'frank', action: 'LOGIN', timestamp: '2026-03-29T00:00:00Z', details: {} }])
  await routeJson(page, '**/api/introspection/system-health', {
    status: 'ok',
    database: 'ok',
    active_jobs: 1,
    cpu_percent: 12.5,
    memory_percent: 40.2,
    memory_used_bytes: 2147483648,
    memory_total_bytes: 4294967296,
    disk_read_bytes: 1024,
    disk_write_bytes: 2048,
    worker_queue_size: 0,
  })
  await routeJson(page, '**/api/admin/configuration', {
    settings: [
      { key: 'log_level', value: 'INFO', requires_restart: false },
      { key: 'log_format', value: 'text', requires_restart: false },
      { key: 'log_file', value: '/var/log/ecube/app.log', requires_restart: false },
      { key: 'log_file_max_bytes', value: 10485760, requires_restart: false },
      { key: 'log_file_backup_count', value: 5, requires_restart: false },
      { key: 'db_pool_size', value: 5, requires_restart: false },
      { key: 'db_pool_max_overflow', value: 10, requires_restart: false },
      { key: 'db_pool_recycle_seconds', value: -1, requires_restart: true },
    ],
  })
  await routeJson(page, '**/api/jobs/55', { id: 55, project_id: 'PRJ', evidence_number: 'EV', status: 'RUNNING', copied_bytes: 20, total_bytes: 100 })
  await routeJson(page, '**/api/jobs/55/files', { files: [] })
  await routeJson(page, '**/api/introspection/jobs/55/debug', { files: [] })
}

test('theme switch changes css variables', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await mockCoreApis(page)

  await page.goto('/')

  const before = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim())

  // Disable CSS transitions so the theme change is instant (avoids mid-transition color values
  // during the a11y scan when body color animates over 0.5 s in base.css).
  await page.addStyleTag({ content: '*, *::before, *::after { transition-duration: 0s !important; animation-duration: 0s !important; }' })
  await page.locator('.theme-select').selectOption('dark')

  // Wait for dark theme CSS to fully settle (all variables must reflect dark values)
  await page.waitForFunction(
    (lightBgPrimary) => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim() !== lightBgPrimary,
    before,
  )
  // Allow two paint cycles so all cascaded variables fully propagate (webkit needs this)
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))

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
    { path: '/mounts', name: 'mounts' },
    { path: '/users', name: 'users' },
    { path: '/system', name: 'system' },
    { path: '/configuration', name: 'configuration' },
    { path: '/jobs/55', name: 'job-detail' },
    { path: '/audit', name: 'audit' },
  ]

  for (const shot of shots) {
    await page.goto(shot.path)
    await expect(page).toHaveScreenshot(`${shot.name}-default.png`)
  }

  await page.goto('/')

  // Disable CSS transitions so the theme change is instant (avoids mid-transition colour values
  // that cause a11y color-contrast failures and incorrect screenshots).
  await page.addStyleTag({ content: '*, *::before, *::after { transition-duration: 0s !important; animation-duration: 0s !important; }' })
  await page.locator('.theme-select').selectOption('dark')

  // Wait for localStorage to be written — this confirms the dark.css onload has fired and
  // the preference is committed. Waiting only for the CSS variable is insufficient because
  // the variable changes just before onload (before localStorage.setItem('dark') runs), and
  // an immediate page.goto() can race past that write.
  await page.waitForFunction(() => localStorage.getItem('ecube_theme') === 'dark')

  const darkBgPrimary = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim()
  )

  for (const shot of shots) {
    await page.goto(shot.path)
    // After each navigation the app re-reads localStorage ('dark') and reloads dark.css;
    // wait until --color-bg-primary matches the known dark value before screenshotting.
    await page.waitForFunction(
      (darkBg) => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim() === darkBg,
      darkBgPrimary,
    )
    // Double RAF: ensures all cascaded CSS variable updates are rendered (webkit needs two frames)
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
    await expect(page).toHaveScreenshot(`${shot.name}-dark.png`)
  }

  // Accessibility scan on last page covered by visual regression
  await expectNoCriticalA11yViolations(page)
})
