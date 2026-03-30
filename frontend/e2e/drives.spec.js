import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

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
  await page.getByRole('button', { name: 'Open' }).click()

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
