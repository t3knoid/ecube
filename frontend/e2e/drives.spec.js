import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

// ---------------------------------------------------------------------------
// Shared fixture for a historically known drive row.
// Override to DISABLED plus filesystem_path when discovery has physically
// detected the device on a known port but the port is blocked.
// ---------------------------------------------------------------------------
function makeEmptyDrive(overrides = {}) {
  return {
    id: 2,
    device_identifier: '/dev/sdc',
    display_device_label: 'SanDisk Ultra - Port 7',
    manufacturer: 'SanDisk',
    product_name: 'Ultra',
    port_number: 7,
    port_system_path: '2-7',
    serial_number: 'SER-002',
    filesystem_path: null,
    filesystem_type: null,
    capacity_bytes: 1073741824,
    current_state: 'DISCONNECTED',
    current_project_id: null,
    port_id: 7,
    ...overrides,
  }
}

async function stubDriveDetailApis(page, drive) {
  await routeJson(page, '**/api/drives', () => [drive])
  await routeJson(page, '**/api/jobs**', [])
}

async function gotoDriveDetail(page, driveId) {
  await page.goto(`/drives/${driveId}`)
  await expect(page.locator('.detail-card')).toBeVisible({ timeout: 10000 })
}

// ---------------------------------------------------------------------------
// Enable Drive — button visibility
// ---------------------------------------------------------------------------

test('Enable Drive button is visible for admin on a physically detected DISABLED drive', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  const drive = makeEmptyDrive({ current_state: 'DISABLED', filesystem_path: '/dev/sdc' })
  await stubDriveDetailApis(page, drive)

  await gotoDriveDetail(page, 2)
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toBeVisible({ timeout: 10000 })
})

test('Enable Drive button is visible for manager on a physically detected DISABLED drive', async ({ page }) => {
  await setupAuthenticatedPage(page, ['manager'])
  const drive = makeEmptyDrive({ current_state: 'DISABLED', filesystem_path: '/dev/sdc' })
  await stubDriveDetailApis(page, drive)

  await gotoDriveDetail(page, 2)
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toBeVisible({ timeout: 10000 })
})

test('Enable Drive button is not visible for admin when the drive is disconnected and not physically detected', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  const drive = makeEmptyDrive()
  await stubDriveDetailApis(page, drive)

  await gotoDriveDetail(page, 2)
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toHaveCount(0)
})

test('Enable Drive button is not visible for processor on DISCONNECTED drive', async ({ page }) => {
  await setupAuthenticatedPage(page, ['processor'])
  const drive = makeEmptyDrive()
  await stubDriveDetailApis(page, drive)

  await gotoDriveDetail(page, 2)
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toHaveCount(0)
})

test('Enable Drive button is not visible when drive has no port_id', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  const drive = makeEmptyDrive({ port_id: null })
  await stubDriveDetailApis(page, drive)

  await gotoDriveDetail(page, 2)
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toHaveCount(0)
})

test('Enable Drive button is not visible when drive is AVAILABLE', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  const drive = makeEmptyDrive({ current_state: 'AVAILABLE' })
  await stubDriveDetailApis(page, drive)

  await gotoDriveDetail(page, 2)
  await expect(page.getByRole('button', { name: 'Enable Drive' })).toHaveCount(0)
})

// ---------------------------------------------------------------------------
// Enable Drive — API calls and success banner
// ---------------------------------------------------------------------------

test('Enable Drive issues PATCH port + POST refresh and shows success banner when drive becomes AVAILABLE', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = makeEmptyDrive({ current_state: 'DISABLED', filesystem_path: '/dev/sdc' })

  // Track which API calls were made
  const patchRequests = []
  const patchBodies = []
  const refreshRequests = []

  await stubDriveDetailApis(page, drive)

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

  await gotoDriveDetail(page, 2)
  await page.getByRole('button', { name: 'Enable Drive' }).click()

  await expect(page.getByText('Port enabled. Drive is now available.')).toBeVisible()

  expect(patchRequests).toContain('PATCH')
  expect(patchBodies[0]).toEqual({ enabled: true })
  expect(refreshRequests).toContain('POST')
})

// ---------------------------------------------------------------------------
// Enable Drive — warning banner when drive stays DISABLED after refresh
// ---------------------------------------------------------------------------

test('Enable Drive shows warning banner when drive does not promote to AVAILABLE', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = makeEmptyDrive({ current_state: 'DISABLED', filesystem_path: '/dev/sdc' })

  await stubDriveDetailApis(page, drive)

  // Port enable succeeds but discovery does not promote the drive
  await page.route('**/api/admin/ports/7', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 7, enabled: true }) })
  })
  await page.route('**/api/drives/refresh', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
  })

  await gotoDriveDetail(page, 2)
  await page.getByRole('button', { name: 'Enable Drive' }).click()

  await expect(page.getByText(/Port enabled, but drive is still/)).toBeVisible()
  await expect(page.getByText('Port enabled. Drive is now available.')).toHaveCount(0)
})

test('Enable Drive shows success banner when drive is immediately reconciled to IN_USE', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = makeEmptyDrive({ current_state: 'DISABLED', filesystem_path: '/dev/sdc' })

  await stubDriveDetailApis(page, drive)

  await page.route('**/api/admin/ports/7', async (route) => {
    drive.current_state = 'IN_USE'
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 7, enabled: true }) })
  })
  await page.route('**/api/drives/refresh', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
  })

  await gotoDriveDetail(page, 2)
  await page.getByRole('button', { name: 'Enable Drive' }).click()

  await expect(page.getByText('Port enabled. Drive remains in use because it is already mounted.')).toBeVisible()
  await expect(page.getByText(/Port enabled, but drive is still/)).toHaveCount(0)
})

// ---------------------------------------------------------------------------
// Enable Drive — error banner on API failure
// ---------------------------------------------------------------------------

test('Enable Drive shows error banner when PATCH port call fails', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = makeEmptyDrive({ current_state: 'DISABLED', filesystem_path: '/dev/sdc' })
  await stubDriveDetailApis(page, drive)

  await page.route('**/api/admin/ports/7', async (route) => {
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'internal error' }) })
  })

  await gotoDriveDetail(page, 2)
  await page.getByRole('button', { name: 'Enable Drive' }).click()

  await expect(page.getByText(/Server error/i)).toBeVisible()
  await expect(page.getByText('Port enabled. Drive is now available.')).toHaveCount(0)
})

// ---------------------------------------------------------------------------
// Original admin flows
// ---------------------------------------------------------------------------

test('prepare eject surfaces busy-drive detail without trapping the dialog', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = {
    id: 7,
    device_identifier: '/dev/sdg',
    display_device_label: 'Kingston DataTraveler - Port 8',
    manufacturer: 'Kingston',
    product_name: 'DataTraveler',
    port_number: 8,
    port_system_path: '2-8',
    serial_number: 'SER-007',
    filesystem_path: '/mnt/usb7',
    filesystem_type: 'ext4',
    capacity_bytes: 1073741824,
    current_state: 'IN_USE',
    current_project_id: 'PRJ-777',
    mount_path: '/mnt/ecube/7',
  }

  await routeJson(page, '**/api/drives', () => [drive])
  await routeJson(page, '**/api/jobs**', [])
  await page.route('**/api/drives/7/prepare-eject**', async (route) => {
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Drive is busy; close any shell, file browser, or process using the mounted drive and retry prepare-eject' }),
    })
  })

  await page.goto('/drives/7')
  await page.getByRole('button', { name: 'Prepare Eject' }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: 'Prepare Eject' }).click()

  await expect(page.locator('.error-banner').filter({ hasText: 'Drive is busy; close any shell, file browser, or process using the mounted drive and retry prepare-eject' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('drives list and drive detail admin flows', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const drive = {
    id: 1,
    device_identifier: '/dev/sdb',
    display_device_label: 'SanDisk Ultra - Port 1',
    manufacturer: 'SanDisk',
    product_name: 'Ultra',
    port_number: 1,
    port_system_path: '2-1',
    serial_number: 'SER-001',
    filesystem_path: '/mnt/usb1',
    filesystem_type: 'ext4',
    capacity_bytes: 1073741824,
    current_state: 'AVAILABLE',
    current_project_id: null,
    mount_path: null,
  }

  await routeJson(page, '**/api/drives', () => [drive])
  await routeJson(page, '**/api/jobs**', [])
  await routeJson(page, '**/api/drives/refresh', { ok: true })
  await routeJson(page, '**/api/mounts', [{
    id: 4,
    project_id: 'PRJ-112',
    status: 'MOUNTED',
    remote_path: '10.1.1.1:/share',
    local_mount_point: '/mnt/share',
  }])

  await page.route('**/api/drives/1/format', async (route) => {
    drive.filesystem_type = route.request().postDataJSON().filesystem_type || 'ext4'
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(drive) })
  })
  await page.route('**/api/drives/1/mount', async (route) => {
    drive.mount_path = '/mnt/ecube/1'
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(drive) })
  })
  await page.route('**/api/drives/1/initialize', async (route) => {
    drive.current_project_id = route.request().postDataJSON().project_id
    drive.current_state = 'IN_USE'
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(drive) })
  })
  await page.route('**/api/drives/1/prepare-eject**', async (route) => {
    drive.current_state = 'AVAILABLE'
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(drive) })
  })

  await page.goto('/drives')
  await expect(page.getByRole('heading', { name: 'Drives' })).toBeVisible()
  await expect(page.getByRole('table').getByText('Device')).toBeVisible()
  await expect(page.getByRole('table').getByText('Project')).toBeVisible()
  await expect(page.getByRole('table').getByText('Job ID')).toBeVisible()
  await expect(page.getByText('SanDisk Ultra - Port 1')).toBeVisible()
  await page.getByRole('row').filter({ has: page.getByText('SanDisk Ultra - Port 1') }).getByRole('button', { name: '1' }).click()

  await expect(page).toHaveURL(/\/drives\/1$/)
  await page.getByRole('button', { name: 'Format' }).click()
  await page.getByRole('button', { name: 'Format' }).last().click()
  await expect(page.getByText('Drive format request submitted.')).toBeVisible()

  await page.getByRole('button', { name: 'Mount' }).click()
  await expect(page.getByText('Drive mounted successfully.')).toBeVisible()

  await page.getByRole('button', { name: 'Initialize' }).click()
  await page.locator('#project-id').selectOption('PRJ-112')
  await page.getByRole('button', { name: 'Initialize' }).last().click()
  await expect(page.getByText('Drive initialized successfully.')).toBeVisible()

  await page.getByRole('button', { name: 'Prepare Eject' }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: 'Prepare Eject' }).click()
  await expect(page.getByText('Drive prepared for ejection.')).toBeVisible()

  await expectNoCriticalA11yViolations(page)
})

test('drives mobile overflow menu stays visible without expanding the row', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await setupAuthenticatedPage(page, ['admin'])

  const drive = {
    id: 1,
    device_identifier: '/dev/sdb',
    display_device_label: 'SanDisk Ultra - Port 1',
    manufacturer: 'SanDisk',
    product_name: 'Ultra',
    port_number: 1,
    port_system_path: '2-1',
    serial_number: 'SER-001',
    filesystem_path: '/mnt/usb1',
    filesystem_type: 'ext4',
    capacity_bytes: 1073741824,
    current_state: 'AVAILABLE',
    current_project_id: null,
    mount_path: '/mnt/ecube/1',
  }

  await routeJson(page, '**/api/drives', () => [drive])
  await routeJson(page, '**/api/jobs**', [])

  await page.goto('/drives')
  await expect(page.getByRole('heading', { name: 'Drives' })).toBeVisible()

  const row = page.locator('tbody tr').first()
  const rowBoxBefore = await row.boundingBox()

  const toggle = page.getByLabel('SanDisk Ultra - Port 1 drive actions')
  await toggle.click()

  const popover = page.locator('.row-actions-popover').first()
  await expect(popover).toBeVisible()
  const popoverBox = await popover.boundingBox()

  const rowBoxAfter = await row.boundingBox()

  expect(rowBoxBefore).not.toBeNull()
  expect(popoverBox).not.toBeNull()
  expect(rowBoxAfter).not.toBeNull()
  expect(popoverBox.x).toBeGreaterThanOrEqual(0)
  expect(popoverBox.y).toBeGreaterThanOrEqual(0)
  expect(popoverBox.x + popoverBox.width).toBeLessThanOrEqual(391)
  expect(popoverBox.y + popoverBox.height).toBeLessThanOrEqual(845)
  expect(Math.abs(rowBoxAfter.height - rowBoxBefore.height)).toBeLessThanOrEqual(1)
})
