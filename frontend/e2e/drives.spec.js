import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

// ---------------------------------------------------------------------------
// Shared fixture for an EMPTY drive with a known port_id
// ---------------------------------------------------------------------------
function makeEmptyDrive(overrides = {}) {
  return {
    id: 2,
    device_identifier: '/dev/sdc',
    filesystem_path: null,
    filesystem_type: null,
    capacity_bytes: 1073741824,
    current_state: 'EMPTY',
    current_project_id: null,
    port_id: 7,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Enable Drive — button visibility
// ---------------------------------------------------------------------------

test('Enable Drive button is visible for admin on EMPTY drive with port_id', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  const drive = makeEmptyDrive()
  await routeJson(page, '**/api/drives', () => [drive])

  await page.goto('/drives/2')
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toBeVisible()
})

test('Enable Drive button is visible for manager on EMPTY drive with port_id', async ({ page }) => {
  await setupAuthenticatedPage(page, ['manager'])
  const drive = makeEmptyDrive()
  await routeJson(page, '**/api/drives', () => [drive])

  await page.goto('/drives/2')
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toBeVisible()
})

test('Enable Drive button is not visible for processor', async ({ page }) => {
  await setupAuthenticatedPage(page, ['processor'])
  const drive = makeEmptyDrive()
  await routeJson(page, '**/api/drives', () => [drive])

  await page.goto('/drives/2')
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toHaveCount(0)
})

test('Enable Drive button is not visible when drive has no port_id', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  const drive = makeEmptyDrive({ port_id: null })
  await routeJson(page, '**/api/drives', () => [drive])

  await page.goto('/drives/2')
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toHaveCount(0)
})

test('Enable Drive button is not visible when drive is AVAILABLE', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  const drive = makeEmptyDrive({ current_state: 'AVAILABLE' })
  await routeJson(page, '**/api/drives', () => [drive])

  await page.goto('/drives/2')
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toHaveCount(0)
})

// ---------------------------------------------------------------------------
// Enable Drive — API calls and success banner
// ---------------------------------------------------------------------------

test('Enable Drive issues PATCH port + POST refresh and shows success banner when drive becomes AVAILABLE', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = makeEmptyDrive()

  // Track which API calls were made
  const patchRequests = []
  const patchBodies = []
  const refreshRequests = []

  await routeJson(page, '**/api/drives', () => [drive])

  await page.route('**/api/admin/ports/7', async (route) => {
    patchRequests.push(route.request().method())
    patchBodies.push(route.request().postDataJSON())
    drive.current_state = 'AVAILABLE'
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 7, enabled: true }) })
  })

  await page.route('**/api/drives/refresh', async (route) => {
    refreshRequests.push(route.request().method())
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
  })

  await page.goto('/drives/2')
  await page.getByRole('button', { name: 'Enable Drive' }).click()

  await expect(page.getByText('Port enabled. Drive is now available.')).toBeVisible()

  expect(patchRequests).toContain('PATCH')
  expect(patchBodies[0]).toEqual({ enabled: true })
  expect(refreshRequests).toContain('POST')
})

// ---------------------------------------------------------------------------
// Enable Drive — warning banner when drive stays EMPTY after refresh
// ---------------------------------------------------------------------------

test('Enable Drive shows warning banner when drive does not promote to AVAILABLE', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = makeEmptyDrive()

  await routeJson(page, '**/api/drives', () => [drive])

  // Port enable succeeds but discovery does not promote the drive
  await page.route('**/api/admin/ports/7', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 7, enabled: true }) })
  })
  await page.route('**/api/drives/refresh', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
  })

  await page.goto('/drives/2')
  await page.getByRole('button', { name: 'Enable Drive' }).click()

  await expect(page.getByText(/Port enabled, but drive is still/)).toBeVisible()
  await expect(page.getByText('Port enabled. Drive is now available.')).toHaveCount(0)
})

// ---------------------------------------------------------------------------
// Enable Drive — error banner on API failure
// ---------------------------------------------------------------------------

test('Enable Drive shows error banner when PATCH port call fails', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = makeEmptyDrive()
  await routeJson(page, '**/api/drives', () => [drive])

  await page.route('**/api/admin/ports/7', async (route) => {
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'internal error' }) })
  })

  await page.goto('/drives/2')
  await page.getByRole('button', { name: 'Enable Drive' }).click()

  await expect(page.getByText(/Server error/i)).toBeVisible()
  await expect(page.getByText('Port enabled. Drive is now available.')).toHaveCount(0)
})

// ---------------------------------------------------------------------------
// Original admin flows
// ---------------------------------------------------------------------------

test('drives list and drive detail admin flows', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = {
    id: 1,
    device_identifier: '/dev/sdb',
    filesystem_path: '/mnt/usb1',
    filesystem_type: 'ext4',
    capacity_bytes: 1073741824,
    current_state: 'AVAILABLE',
    current_project_id: null,
  }

  await routeJson(page, '**/api/drives', () => [drive])
  await routeJson(page, '**/api/drives/refresh', { ok: true })

  await page.route('**/api/drives/1/format', async (route) => {
    drive.filesystem_type = route.request().postDataJSON().filesystem_type || 'ext4'
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(drive) })
  })
  await page.route('**/api/drives/1/initialize', async (route) => {
    drive.current_project_id = route.request().postDataJSON().project_id
    drive.current_state = 'IN_USE'
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(drive) })
  })
  await page.route('**/api/drives/1/prepare-eject', async (route) => {
    drive.current_state = 'AVAILABLE'
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(drive) })
  })

  await page.goto('/drives')
  await expect(page.getByRole('heading', { name: 'Drives' })).toBeVisible()
  await page.getByRole('button', { name: 'Details' }).click()

  await expect(page).toHaveURL(/\/drives\/1$/)
  await page.getByRole('button', { name: 'Format' }).click()
  await page.getByRole('button', { name: 'Format' }).last().click()
  await expect(page.getByText('Drive format request submitted.')).toBeVisible()

  await page.getByRole('button', { name: 'Initialize' }).first().click()
  await page.getByLabel('Project').fill('PRJ-112')
  await page.getByRole('button', { name: 'Initialize' }).last().click()
  await expect(page.getByText('Drive initialized successfully.')).toBeVisible()

  await page.getByRole('button', { name: 'Prepare Eject' }).first().click()
  await page.getByRole('button', { name: 'Prepare Eject' }).last().click()
  await expect(page.getByText('Drive prepared for ejection.')).toBeVisible()

  await expectNoCriticalA11yViolations(page)
})
