import { test, expect } from '@playwright/test'
import { makeToken, routeJson, stubSetupStatus, stubFooterApis } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('login success, login failure, and session expiry banner', async ({ page }) => {
  await stubSetupStatus(page, true)
  await stubFooterApis(page)
  await routeJson(page, '**/api/drives', [])
  await routeJson(page, '**/api/jobs**', [])

  await page.route('**/api/auth/token', async (route) => {
    const postData = route.request().postDataJSON()
    if (postData.username === 'good' && postData.password === 'pass') {
      const token = makeToken({ sub: 'good', roles: ['admin'], groups: [], exp: Math.floor(Date.now() / 1000) + 3600 })
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: token }) })
      return
    }

    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Invalid username or password.' }),
    })
  })

  await page.goto('/login')
  await page.getByLabel('Username').fill('bad')
  await page.getByLabel('Password').fill('creds')
  await page.getByRole('button', { name: 'Log In' }).click()
  await expect(page.getByRole('alert')).toContainText('Invalid username or password.')

  await page.getByLabel('Username').fill('good')
  await page.getByLabel('Password').fill('pass')
  await page.getByRole('button', { name: 'Log In' }).click()
  await expect(page).toHaveURL(/\/$/)

  await page.goto('/login?expired=1')
  await expect(page.getByText('Session Expired')).toBeVisible()

  await expectNoCriticalA11yViolations(page)
})
