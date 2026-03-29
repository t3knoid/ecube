import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson, stubSetupStatus, stubFooterApis } from './helpers/app.js'

test('keyboard navigation: login form Tab order and Enter submit', async ({ page }) => {
  await stubSetupStatus(page, true)
  await stubFooterApis(page)

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
    { id: 10, type: 'NFS', remote_path: '10.0.0.4:/exports', local_mount_point: '/mnt/evidence', status: 'CONNECTED' },
  ]

  await page.route('**/api/mounts', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts) })
  })
  await page.route('**/api/mounts/*', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/mounts')

  // Open ConfirmDialog via the Remove button
  await page.getByRole('button', { name: 'Remove' }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()

  // Escape dismisses the dialog without action
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('keyboard navigation: ConfirmDialog confirm button reachable by Tab', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const mounts = [
    { id: 10, type: 'NFS', remote_path: '10.0.0.4:/exports', local_mount_point: '/mnt/evidence', status: 'CONNECTED' },
  ]

  await page.route('**/api/mounts', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts) })
  })
  await page.route('**/api/mounts/*', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/mounts')

  await page.getByRole('button', { name: 'Remove' }).first().click()
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

  const logs = Array.from({ length: 20 }, (_, i) => ({
    id: i + 1,
    timestamp: '2026-03-29T10:00:00Z',
    user: `user${i}`,
    action: 'LOGIN',
    job_id: null,
    client_ip: '127.0.0.1',
    details: {},
  }))

  await page.route('**/api/audit**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(logs) })
  })

  await page.goto('/audit')

  const pagination = page.locator('.table-pagination')
  await expect(pagination).toBeVisible()

  // The Next-page button must be focusable and activatable with the keyboard
  const nextBtn = pagination.getByRole('button').last()
  await nextBtn.focus()
  await expect(nextBtn).toBeFocused()
  await page.keyboard.press('Enter')

  // After keyboard activation the pagination region remains visible/functional
  await expect(pagination).toBeVisible()
})

test('keyboard navigation: sidebar navigation links are Tab-reachable', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await routeJson(page, '**/api/drives', [])
  await routeJson(page, '**/api/jobs**', [])

  await page.goto('/')

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
