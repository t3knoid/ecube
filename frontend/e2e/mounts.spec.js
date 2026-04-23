import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('mounts add/edit/test/remove flow', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const mounts = [{ id: 10, type: 'NFS', remote_path: '10.0.0.4:/exports', local_mount_point: '/nfs/exports', project_id: 'CASE-2026-000', status: 'MOUNTED' }]
  const patchPayloads = []

  await page.route('**/api/mounts', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts) })
      return
    }
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      mounts.push({
        id: 11,
        status: 'MOUNTED',
        local_mount_point: '/nfs/case-2026-001',
        last_checked_at: null,
        ...body,
      })
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
    if (route.request().method() === 'PATCH') {
      const mountId = Number(route.request().url().split('/').pop())
      const body = route.request().postDataJSON()
      patchPayloads.push(body)
      const index = mounts.findIndex((mount) => mount.id === mountId)
      mounts[index] = { ...mounts[index], ...body, status: 'MOUNTED' }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts[index]) })
      return
    }
    if (route.request().method() === 'DELETE') {
      mounts.splice(0, 1)
      await route.fulfill({ status: 204, contentType: 'application/json', body: '' })
      return
    }
    await route.fallback()
  })

  await page.goto('/mounts')
  await expect(page.getByRole('heading', { name: 'Mounts' })).toBeVisible()

  await page.getByRole('button', { name: 'Add Mount' }).click()
  await expect(page.getByRole('heading', { name: 'Add Share' })).toBeVisible()
  await page.getByLabel('Remote Path').fill('10.0.0.8:/cases')
  await page.getByLabel('Project').fill('case-2026-001')
  await page.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByText('CASE-2026-001')).toBeVisible()

  await page.getByRole('button', { name: 'Edit' }).nth(1).click()
  await expect(page.getByRole('heading', { name: 'Edit Share' })).toBeVisible()
  await expect(page.getByLabel('Local Mount Point')).toHaveValue('/nfs/case-2026-001')
  await page.getByLabel('Remote Path').fill('//server/case-2026-001')
  await expect(page.getByRole('button', { name: 'Clear saved credentials' })).toBeVisible()
  await page.getByRole('button', { name: 'Clear saved credentials' }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()

  expect(patchPayloads).toEqual([
    {
      type: 'NFS',
      remote_path: '//server/case-2026-001',
      project_id: 'CASE-2026-001',
      username: null,
      password: null,
      credentials_file: null,
    },
  ])

  await page.getByRole('button', { name: 'Test' }).nth(1).click()

  await page.getByRole('button', { name: 'Remove' }).first().click()
  await page.getByRole('button', { name: 'Remove' }).last().click()

  await expectNoCriticalA11yViolations(page)
})
