import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('mounts add/test/remove flow', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const mounts = [{ id: 10, type: 'NFS', remote_path: '10.0.0.4:/exports', local_mount_point: '/mnt/evidence', status: 'CONNECTED' }]

  await page.route('**/api/mounts', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts) })
      return
    }
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      mounts.push({ id: 11, status: 'CONNECTED', ...body })
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts[mounts.length - 1]) })
      return
    }
    await route.fallback()
  })

  await page.route('**/api/mounts/validate', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts) })
  })

  await page.route('**/api/mounts/*/validate', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts[0]) })
  })

  await page.route('**/api/mounts/*', async (route) => {
    if (route.request().method() === 'DELETE') {
      mounts.splice(0, 1)
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.fallback()
  })

  await page.goto('/mounts')
  await expect(page.getByRole('heading', { name: 'Mounts' })).toBeVisible()

  await page.getByRole('button', { name: 'Add Mount' }).click()
  await page.getByLabel('Remote Path').fill('10.0.0.8:/cases')
  await page.getByLabel('Local Mount Point').fill('/mnt/cases')
  await page.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByText('10.0.0.8:/cases')).toBeVisible()

  await page.getByRole('button', { name: 'Test' }).first().click()
  await page.getByRole('button', { name: 'Remove' }).first().click()
  await page.getByRole('button', { name: 'Remove' }).last().click()

  await expectNoCriticalA11yViolations(page)
})
