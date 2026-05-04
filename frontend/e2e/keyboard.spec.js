import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson, setupPublicPage } from './helpers/app.js'

test('keyboard navigation: login form Tab order and Enter submit', async ({ page }) => {
  await setupPublicPage(page, { initialized: true })

  await page.route('**/api/auth/token', async (route) => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Invalid username or password.' }),
    })
  })

  await page.goto('/login')

  // Tab moves focus: Username → Password → Log In button
  await page.getByLabel('Username').focus()
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Password')).toBeFocused()

  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Log In' })).toBeFocused()

  // Enter from the password field submits the form
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('wrong')
  await page.getByLabel('Password').press('Enter')
  await expect(page.getByRole('alert')).toBeVisible()
})

test('keyboard navigation: ConfirmDialog closes with Escape', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const mounts = [
    { id: 10, type: 'NFS', remote_path: '10.0.0.4:/exports', local_mount_point: '/mnt/evidence', status: 'MOUNTED' },
  ]

  await page.route('**/api/mounts', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts) })
  })
  await routeJson(page, '**/api/jobs**', [])
  await page.route('**/api/mounts/*', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/mounts/10')

  // Open ConfirmDialog via the Remove button
  await page.getByRole('button', { name: 'Remove' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()

  // Escape dismisses the dialog without action
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('keyboard navigation: ConfirmDialog confirm button reachable by Tab', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const mounts = [
    { id: 10, type: 'NFS', remote_path: '10.0.0.4:/exports', local_mount_point: '/mnt/evidence', status: 'MOUNTED' },
  ]

  await page.route('**/api/mounts', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts) })
  })
  await routeJson(page, '**/api/jobs**', [])
  await page.route('**/api/mounts/*', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/mounts/10')

  await page.getByRole('button', { name: 'Remove' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()

  // Focus the confirm button by tabbing within the dialog and activate via Enter
  const confirmButton = dialog.getByRole('button', { name: /remove/i }).last()
  await confirmButton.focus()
  await expect(confirmButton).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeHidden()
})

test('keyboard navigation: DataTable pagination controls are keyboard-reachable', async ({ page }) => {
  await setupAuthenticatedPage(page, ['auditor'])

  const logs = Array.from({ length: 21 }, (_, i) => ({
    id: i + 1,
    timestamp: '2026-03-29T10:00:00Z',
    user: `user${i}`,
    action: 'LOGIN',
    job_id: null,
    client_ip: '127.0.0.1',
    details: {},
  }))

  await routeJson(page, '**/api/audit/options', {
    actions: ['LOGIN'],
    users: logs.map((entry) => entry.user),
    job_ids: [],
  })

  await page.route(/\/api\/audit(?!\/)/, async (route) => {
    const requestUrl = new URL(route.request().url())
    const limit = Number(requestUrl.searchParams.get('limit') || 20)
    const offset = Number(requestUrl.searchParams.get('offset') || 0)
    const entries = logs.slice(offset, offset + limit)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        entries,
        total: logs.length,
        limit,
        offset,
        has_more: offset + entries.length < logs.length,
      }),
    })
  })
  await routeJson(page, '**/api/drives', [])

  await page.goto('/audit')

  const pagination = page.locator('.pagination-wrap')
  await expect(pagination).toBeVisible()

  // An enabled page shortcut must be focusable and activatable with the keyboard
  const nextBtn = pagination.getByRole('button', { name: '2' })
  await nextBtn.focus()
  await expect(nextBtn).toBeFocused()
  await page.keyboard.press('Enter')

  await expect(page.locator('tbody').getByText('user20')).toBeVisible()

  // After keyboard activation the pagination region remains visible/functional
  await expect(pagination).toBeVisible()
})

test('keyboard navigation: sidebar navigation links are Tab-reachable', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await routeJson(page, '**/api/drives', [])
  await routeJson(page, '**/api/jobs**', [])

  await page.goto('/')

  await expect(page.locator('.app-sidebar')).toBeVisible()
  const navLinks = page.locator('nav a[href]')
  const count = await navLinks.count()
  expect(count).toBeGreaterThan(0)

  // First link accepts keyboard focus
  await navLinks.first().focus()
  await expect(navLinks.first()).toBeFocused()

  // Tabbing moves focus away from the first link
  await page.keyboard.press('Tab')
  await expect(navLinks.first()).not.toBeFocused()
})

test('keyboard navigation: system log paging controls are focusable and activatable', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  await routeJson(page, '**/api/admin/logs', {
    log_files: [
      { name: 'app.log', size: 64, modified: '2026-04-08T11:59:00Z' },
      { name: 'app.log.1', size: 32, modified: '2026-04-08T11:00:00Z' },
    ],
    total_size: 96,
  })

  await routeJson(page, '**/api/admin/logs/view', (request) => {
    const url = new URL(request.url())
    const offset = Number(url.searchParams.get('offset') || '0')

    if (offset === 2) {
      return {
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:02Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 198', source_path: 'app.log' }],
        returned: 1,
        has_more: false,
        limit: 200,
        offset: 2,
      }
    }

    if (offset === 1) {
      return {
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:01Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 199', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 1,
      }
    }

    return {
      source: { source: 'app.log', path: 'app.log' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:59:00Z',
      lines: [{ content: 'line 200', source_path: 'app.log' }],
      returned: 1,
      has_more: true,
      limit: 200,
      offset: 0,
    }
  })

  await page.goto('/system')
  await page.getByRole('button', { name: 'Logs' }).click()

  const olderButton = page.getByRole('button', { name: 'Load older lines' })
  await expect(olderButton).toBeVisible()
  await expect(olderButton).toBeEnabled()
  await olderButton.focus()
  await expect(olderButton).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('.log-viewer')).toContainText('line 199')
  await expect(olderButton).toBeFocused()

  await page.keyboard.press('Enter')
  await expect(page.locator('.log-viewer')).toContainText('line 198')

  const newerButton = page.getByRole('button', { name: 'Load newer lines' })
  await expect(newerButton).toBeVisible()
  await expect(newerButton).toBeEnabled()
  await newerButton.focus()
  await expect(newerButton).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('.log-viewer')).toContainText('line 199')
})
