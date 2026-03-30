import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('users list, role assignment, and create os user', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const roleUsers = { users: [{ username: 'alba', roles: ['processor'] }] }
  const osUsers = { users: [{ username: 'alba', uid: 1001, gid: 1001, home: '/home/alba', shell: '/bin/bash', groups: ['ecube-processors'] }] }

  await page.route('**/api/users', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(roleUsers) })
  })
  await page.route('**/api/admin/os-users', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(osUsers) })
      return
    }
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.fallback()
  })
  await page.route('**/api/users/alba/roles', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ username: 'alba', roles: ['manager'] }) })
  })

  await page.goto('/users')

  const row = page.getByRole('row').filter({ hasText: 'alba' })
  await row.getByRole('checkbox', { name: 'Manager' }).check()
  await row.getByRole('button', { name: 'Save' }).click()

  await page.getByRole('button', { name: 'Create User' }).click()
  await page.getByLabel('Username').fill('newuser')
  await page.getByLabel('Password').first().fill('StrongPass123!')
  await page.getByRole('dialog').getByRole('button', { name: 'Create' }).click()

  await expectNoCriticalA11yViolations(page)
})
