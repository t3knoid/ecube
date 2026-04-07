import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

async function disableMotion(page) {
  await page.addStyleTag({ content: '*, *::before, *::after { transition-duration: 0s !important; animation-duration: 0s !important; }' })
}

async function waitForStablePaint(page) {
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
}

async function mockTelemetry(page) {
  await routeJson(page, '**/api/ui/telemetry', { ok: true })
}

async function mockSetupApis(page) {
  await routeJson(page, '**/api/setup/status', { initialized: false })
  await routeJson(page, '**/api/setup/database/provision-status', { provisioned: false })
  await routeJson(page, '**/api/setup/database/system-info', { in_docker: false, suggested_db_host: 'localhost' })
}

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

async function openCreateJobWizard(page) {
  await page.goto('/jobs')
  await page.getByRole('button', { name: /create/i }).click()
  await expect(page.locator('.dialog-panel')).toBeVisible()
}

test('theme switch changes css variables', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await mockTelemetry(page)
  await mockCoreApis(page)

  await page.goto('/')

  const before = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim())

  // Disable transitions to avoid sampling colors mid-animation.
  await disableMotion(page)
  await page.locator('.theme-select').selectOption('dark')

  // Wait for dark theme CSS to fully settle (all variables must reflect dark values)
  await page.waitForFunction(
    (lightBgPrimary) => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim() !== lightBgPrimary,
    before,
  )
  // Allow two paint cycles so cascaded variables fully propagate.
  await waitForStablePaint(page)

  const after = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim())
  expect(before).not.toBe(after)
  await expectNoCriticalA11yViolations(page)
})

test('visual regression snapshots for setup screen in default and dark themes', async ({ page }) => {
  await mockTelemetry(page)
  await mockSetupApis(page)

  await page.goto('/setup')
  await expect(page.locator('.setup-card')).toBeVisible()
  await expect(page).toHaveScreenshot('setup-default.png')

  await disableMotion(page)
  await page.locator('.theme-select').selectOption('dark')
  await page.waitForFunction(() => localStorage.getItem('ecube_theme') === 'dark')
  await waitForStablePaint(page)
  await expect(page).toHaveScreenshot('setup-dark.png')
})

test('visual regression snapshots for key screens in default and dark themes', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await mockTelemetry(page)
  await mockCoreApis(page)

  const shots = [
    { path: '/login', name: 'login' },
    { path: '/', name: 'dashboard' },
    { path: '/drives', name: 'drives' },
    { path: '/mounts', name: 'mounts' },
    { path: '/users', name: 'users' },
    { path: '/system', name: 'system' },
    { path: '/configuration', name: 'configuration' },
    { path: '/jobs', name: 'jobs-list' },
    { path: '/jobs/55', name: 'job-detail' },
    { path: '/audit', name: 'audit' },
  ]

  for (const shot of shots) {
    if (shot.name === 'jobs-list') {
      await openCreateJobWizard(page)
    } else {
      await page.goto(shot.path)
    }
    await waitForStablePaint(page)
    await expect(page).toHaveScreenshot(`${shot.name}-default.png`)
  }

  await page.goto('/')

  // Disable transitions so screenshots are stable across theme changes.
  await disableMotion(page)
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
    if (shot.name === 'jobs-list') {
      await openCreateJobWizard(page)
    } else {
      await page.goto(shot.path)
    }
    // After each navigation the app re-reads localStorage ('dark') and reloads dark.css;
    // wait until --color-bg-primary matches the known dark value before screenshotting.
    await page.waitForFunction(
      (darkBg) => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim() === darkBg,
      darkBgPrimary,
    )
    // Double RAF ensures all cascaded CSS variable updates are rendered.
    await waitForStablePaint(page)
    await expect(page).toHaveScreenshot(`${shot.name}-dark.png`)
  }

  // Accessibility scan on last page covered by visual regression
  await expectNoCriticalA11yViolations(page)
})
