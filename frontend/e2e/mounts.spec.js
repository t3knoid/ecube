import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('mounts add/edit/test/remove flow', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 620 })
  await setupAuthenticatedPage(page, ['admin'])

  const mounts = [{ id: 10, type: 'NFS', remote_path: '10.0.0.4:/exports', local_mount_point: '/nfs/exports', project_id: 'CASE-2026-000', status: 'MOUNTED' }]
  const createPayloads = []
  const patchPayloads = []
  const candidateValidatePayloads = []
  const validatePayloads = []

  await page.route('**/api/mounts', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts) })
      return
    }
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      createPayloads.push(body)
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

  await page.route('**/api/mounts/test', async (route) => {
    const body = route.request().postDataJSON()
    candidateValidatePayloads.push(body)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 999,
        ...body,
        local_mount_point: '/nfs/cases',
        status: 'MOUNTED',
        last_checked_at: null,
      }),
    })
  })

  await page.route('**/api/mounts/*/validate', async (route) => {
    const mountId = Number(route.request().url().split('/').slice(-2, -1)[0])
    const body = route.request().postDataJSON() ?? null
    if (body) {
      validatePayloads.push(body)
    }
    const mount = mounts.find((entry) => entry.id === mountId) ?? mounts[0]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mount,
        ...(body ?? {}),
        status: 'MOUNTED',
        last_checked_at: null,
      }),
    })
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
  await expect(page.getByRole('button', { name: 'Test All' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Test', exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: 'Add Mount' }).click()
  await expect(page.getByRole('heading', { name: 'Add Share' })).toBeVisible()
  const addDialog = page.getByRole('dialog', { name: 'Add Share' })
  await page.getByLabel('Remote Path').fill('10.0.0.8:/cases')
  await page.getByLabel('Project').fill('case-2026-001')
  await expect(addDialog.getByRole('button', { name: 'Create', exact: true })).toBeDisabled()
  await addDialog.getByRole('button', { name: 'Test', exact: true }).click()
  await expect(addDialog.getByText('Share test passed. You can now save these changes.')).toBeVisible()
  await expect(addDialog.getByRole('button', { name: 'Create', exact: true })).toBeEnabled()
  await page.getByLabel('Remote Path').fill('10.0.0.8:/cases-updated')
  await expect(addDialog.getByRole('button', { name: 'Create', exact: true })).toBeDisabled()
  await addDialog.getByRole('button', { name: 'Test', exact: true }).click()
  await expect(addDialog.getByRole('button', { name: 'Create', exact: true })).toBeEnabled()
  await addDialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByText('CASE-2026-001')).toBeVisible()

  expect(candidateValidatePayloads).toEqual([
    {
      type: 'SMB',
      remote_path: '10.0.0.8:/cases',
      project_id: 'CASE-2026-001',
      username: null,
      password: null,
      credentials_file: null,
    },
    {
      type: 'SMB',
      remote_path: '10.0.0.8:/cases-updated',
      project_id: 'CASE-2026-001',
      username: null,
      password: null,
      credentials_file: null,
    },
  ])

  expect(createPayloads).toEqual([
    {
      type: 'SMB',
      remote_path: '10.0.0.8:/cases-updated',
      project_id: 'CASE-2026-001',
      username: null,
      password: null,
      credentials_file: null,
    },
  ])

  await page.getByRole('button', { name: 'Edit' }).nth(1).click()
  await expect(page.getByRole('heading', { name: 'Edit Share' })).toBeVisible()
  const editDialog = page.getByRole('dialog', { name: 'Edit Share' })
  await expect(page.getByLabel('Local Mount Point')).toHaveValue('/nfs/case-2026-001')
  await page.getByLabel('Remote Path').fill('//server/case-2026-001')
  await expect(page.getByRole('button', { name: 'Clear saved credentials' })).toBeVisible()
  await page.getByRole('button', { name: 'Clear saved credentials' }).click()
  await expect(editDialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()

  await editDialog.getByRole('button', { name: 'Test', exact: true }).click()
  await expect(editDialog.getByText('Share test passed. You can now save these changes.')).toBeVisible()
  await expect(editDialog.getByRole('button', { name: 'Cancel', exact: true })).toBeInViewport()
  await expect(editDialog.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
  await expect(editDialog.getByRole('button', { name: 'Save', exact: true })).toBeInViewport()

  await page.getByLabel('Remote Path').fill('//server/case-2026-001-updated')
  await expect(editDialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()

  await editDialog.getByRole('button', { name: 'Test', exact: true }).click()
  await expect(editDialog.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()

  await editDialog.getByRole('button', { name: 'Save', exact: true }).click()

  expect(validatePayloads).toEqual([
    {
      type: 'SMB',
      remote_path: '//server/case-2026-001',
      project_id: 'CASE-2026-001',
      username: null,
      password: null,
      credentials_file: null,
    },
    {
      type: 'SMB',
      remote_path: '//server/case-2026-001-updated',
      project_id: 'CASE-2026-001',
      username: null,
      password: null,
      credentials_file: null,
    },
  ])

  expect(patchPayloads).toEqual([
    {
      type: 'SMB',
      remote_path: '//server/case-2026-001-updated',
      project_id: 'CASE-2026-001',
      username: null,
      password: null,
      credentials_file: null,
    },
  ])

  await page.getByRole('button', { name: 'Remove' }).first().click()
  await page.getByRole('button', { name: 'Remove' }).last().click()

  await expectNoCriticalA11yViolations(page)
})

test('mounts mobile overflow menu stays visible without expanding the row', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await setupAuthenticatedPage(page, ['admin'])

  const mounts = [{ id: 10, type: 'SMB', remote_path: '//server/project', local_mount_point: '/smb/project', project_id: 'CASE-2026-001', status: 'MOUNTED' }]

  await page.route('**/api/mounts', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mounts) })
  })

  await page.goto('/mounts')
  await expect(page.getByRole('heading', { name: 'Mounts' })).toBeVisible()

  const row = page.locator('tbody tr').first()
  const rowBoxBefore = await row.boundingBox()

  const toggle = page.getByLabel('CASE-2026-001 mount actions')
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
  expect(popoverBox.x + popoverBox.width).toBeLessThanOrEqual(390)
  expect(popoverBox.y + popoverBox.height).toBeLessThanOrEqual(844)
  expect(Math.abs(rowBoxAfter.height - rowBoxBefore.height)).toBeLessThanOrEqual(1)
})
