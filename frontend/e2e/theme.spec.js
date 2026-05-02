import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson, setupPublicPage } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test.use({ timezoneId: 'America/New_York' })
test.describe.configure({ timeout: 120000 })

async function disableMotion(page) {
  const content = '*, *::before, *::after { transition-duration: 0s !important; animation-duration: 0s !important; animation-delay: 0s !important; scroll-behavior: auto !important; }'
  await page.addInitScript((css) => {
    const styleId = 'pw-disable-motion'
    const ensureStyle = () => {
      if (document.getElementById(styleId)) return
      const style = document.createElement('style')
      style.id = styleId
      style.textContent = css
      document.head.appendChild(style)
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', ensureStyle, { once: true })
    } else {
      ensureStyle()
    }
  }, content)
  await page.addStyleTag({ content })
}

async function waitForStablePaint(page) {
  await page.waitForLoadState('domcontentloaded')
  // WebKit intermittently hangs on requestAnimationFrame-based evaluate calls
  // during rapid screenshot navigation. A short post-load settle is sufficient
  // here because these tests disable motion before theme transitions.
  await page.waitForTimeout(50)
}

async function gotoVisualPage(page, path) {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

async function persistThemeForNextNavigation(page, themeName) {
  await page.addInitScript(({ name }) => {
    localStorage.setItem('ecube_theme', name)
  }, { name: themeName })
  await page.evaluate((name) => {
    localStorage.setItem('ecube_theme', name)
  }, themeName)
}

async function mockSetupApis(page) {
  await setupPublicPage(page, {
    initialized: false,
    provisioned: false,
    systemInfo: {
      in_docker: false,
      suggested_db_host: 'localhost',
      suggested_admin_username: 'postgres',
    },
  })
}

async function mockCoreApis(page) {
  await routeJson(page, '**/api/drives', [{
    id: 1,
    current_state: 'AVAILABLE',
    current_project_id: 'PRJ',
    device_identifier: '/dev/sdb',
    port_system_path: '2-1',
    serial_number: 'SER-001',
    filesystem_type: 'ext4',
    capacity_bytes: 1000,
    mount_path: '/mnt/ecube/1',
  }])
  await routeJson(page, '**/api/mounts', [{
    id: 7,
    project_id: 'PRJ',
    status: 'MOUNTED',
    remote_path: '//server/project',
    local_mount_point: '/nfs/project',
  }])
  await routeJson(page, '**/api/users', { users: [{ username: 'frank', roles: ['admin'] }] })
  await routeJson(page, '**/api/admin/os-users', { users: [{ uid: 1001, username: 'frank', groups: ['ecube-admin'] }] })
  await routeJson(page, '**/api/jobs**', [{ id: 55, project_id: 'PRJ', status: 'RUNNING', copied_bytes: 20, total_bytes: 100, evidence_number: 'EV-055', drive: { id: 1, port_system_path: '2-1', device_identifier: '/dev/sdb' } }])
  await routeJson(page, /\/api\/audit(?!\/)/, [{ id: 1, user: 'frank', action: 'LOGIN', timestamp: '2026-03-29T00:00:00Z', details: {} }])
  await routeJson(page, '**/api/introspection/system-health', {
    status: 'ok',
    database: 'connected',
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
  await routeJson(page, '**/api/jobs/55', { id: 55, project_id: 'PRJ', evidence_number: 'EV', status: 'RUNNING', copied_bytes: 20, total_bytes: 100, drive: { id: 1, port_system_path: '2-1', device_identifier: '/dev/sdb' } })
  await routeJson(page, '**/api/jobs/55/files', { files: [] })
  await routeJson(page, '**/api/jobs/55/chain-of-custody', {
    selector_mode: 'PROJECT',
    project_id: 'PRJ-777',
    snapshot_updated_at: '2026-04-28T15:00:00Z',
    reports: [{
      drive_id: 7,
      drive_sn: 'SN-777',
      drive_manufacturer: 'SanDisk',
      drive_model: 'Extreme Pro',
      project_id: 'PRJ-777',
      evidence_number: 'EV-777',
      custody_complete: true,
      delivery_time: '2026-04-28T14:15:16Z',
      chain_of_custody_events: [
        {
          event_id: 11,
          event_type: 'DRIVE_INITIALIZED',
          timestamp: '2026-04-28T13:00:00Z',
          actor: 'auditor-user',
          action: 'Drive initialized',
          details: { drive_id: 7, project_id: 'PRJ-777' },
        },
        {
          event_id: 12,
          event_type: 'COC_HANDOFF_CONFIRMED',
          timestamp: '2026-04-28T14:15:16Z',
          actor: 'manager-user',
          action: 'Custody handoff confirmed',
          details: {
            possessor: 'Officer Jane Doe',
            received_by: 'Archive Clerk',
            receipt_ref: 'REC-42',
            notes: 'Sealed container intact',
          },
        },
      ],
      manifest_summary: [{
        job_id: 99,
        evidence_number: 'EV-777',
        processor_notes: 'Collected from workstation cart A',
        total_files: 12,
        total_bytes: 4096,
        manifest_count: 2,
        latest_manifest_path: '/reports/manifests/99.json',
        latest_manifest_format: 'json',
        latest_manifest_created_at: '2026-04-28T14:00:00Z',
      }],
    }],
  })
}

async function openCreateJobDialog(page) {
  await gotoVisualPage(page, '/jobs')
  await expect(page.getByRole('heading', { name: 'Jobs' })).toBeVisible()
  const createJobButton = page.getByRole('button', { name: 'Create Job' })
  await expect(createJobButton).toBeVisible()
  await createJobButton.click()
  await expect(page.locator('.dialog-panel')).toBeVisible()
  await page.locator('#job-project').evaluate((element, value) => {
    element.value = value
    element.dispatchEvent(new Event('change', { bubbles: true }))
  }, 'PRJ')
}

async function openCocDialog(page) {
  await gotoVisualPage(page, '/jobs/55')
  await expect(page.getByRole('heading', { name: 'Job Detail #55' })).toBeVisible()
  await page.getByRole('button', { name: 'Chain of Custody' }).click()
  await expect(page.locator('.coc-report-shell')).toBeVisible()
}

async function waitForShotReady(page, shotName) {
  if (shotName === 'login') {
    await expect(page.getByRole('heading', { name: 'ECUBE' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Log In' })).toBeVisible()
    return
  }

  if (shotName === 'dashboard') {
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
    await expect(page.locator('.summary-card').first()).toBeVisible()
    return
  }

  if (shotName === 'drives') {
    await expect(page.getByRole('heading', { name: 'Drives' })).toBeVisible()
    await expect(page.locator('.data-table')).toBeVisible()
    return
  }

  if (shotName === 'mounts') {
    await expect(page.getByRole('heading', { name: 'Mounts' })).toBeVisible()
    await expect(page.locator('.data-table')).toBeVisible()
    return
  }

  if (shotName === 'users') {
    await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible()
    await expect(page.locator('.panel')).toBeVisible()
    return
  }

  if (shotName === 'system') {
    await expect(page.getByRole('heading', { name: 'System' })).toBeVisible()
    await expect(page.locator('.panel, .summary-card').first()).toBeVisible()
    return
  }

  if (shotName === 'configuration') {
    await expect(page.getByRole('heading', { name: 'Configuration' })).toBeVisible()
    await expect(page.locator('form, .panel').first()).toBeVisible()
    return
  }

  if (shotName === 'audit') {
    await expect(page.getByRole('heading', { name: 'Audit' })).toBeVisible()
    await expect(page.locator('table')).toBeVisible()
    return
  }

  if (shotName === 'job-detail') {
    await expect(page.getByRole('heading', { name: 'Job Detail #55' })).toBeVisible()
  }
}

test('theme switch changes css variables', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
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
  await mockSetupApis(page)

  await gotoVisualPage(page, '/setup')
  await expect(page.locator('.setup-card')).toBeVisible()
  const defaultBgPrimary = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim()
  )
  await expect(page).toHaveScreenshot('setup-default.png')

  await disableMotion(page)
  await persistThemeForNextNavigation(page, 'dark')
  await gotoVisualPage(page, '/setup')
  await expect(page.locator('.setup-card')).toBeVisible()
  await page.waitForFunction(() => localStorage.getItem('ecube_theme') === 'dark')
  await page.waitForFunction(
    (lightBgPrimary) => getComputedStyle(document.documentElement).getPropertyValue('--color-bg-primary').trim() !== lightBgPrimary,
    defaultBgPrimary,
  )
  await page.waitForFunction(() => {
    const link = document.getElementById('ecube-theme-stylesheet')
    return Boolean(link && String(link.getAttribute('href') || '').includes('dark.css'))
  })
  await waitForStablePaint(page)
  await expect(page).toHaveScreenshot('setup-dark.png')
})

test('visual regression snapshots for key screens in default and dark themes', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await mockCoreApis(page)
  await disableMotion(page)

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
    { path: '/jobs/55', name: 'coc-report' },
    { path: '/audit', name: 'audit' },
  ]

  for (const shot of shots) {
    if (shot.name === 'jobs-list') {
      await openCreateJobDialog(page)
    } else if (shot.name === 'coc-report') {
      await openCocDialog(page)
    } else {
      await gotoVisualPage(page, shot.path)
      await waitForShotReady(page, shot.name)
    }
    await waitForStablePaint(page)
    await expect(page).toHaveScreenshot(`${shot.name}-default.png`)
  }

  await gotoVisualPage(page, '/')

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
      await openCreateJobDialog(page)
    } else if (shot.name === 'coc-report') {
      await openCocDialog(page)
    } else {
      await gotoVisualPage(page, shot.path)
      await waitForShotReady(page, shot.name)
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
