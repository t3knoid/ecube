import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('jobs create, start, verify, and manifest flow', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  const createdJob = {
    id: 77,
    project_id: 'P-77',
    evidence_number: 'EV-77',
    status: 'PENDING',
    copied_bytes: 0,
    total_bytes: 100,
    thread_count: 4,
  }

  await routeJson(page, '**/api/drives', [{ id: 1, device_identifier: '/dev/sdb' }])
  await routeJson(page, '**/api/mounts', [{ id: 4, remote_path: '10.1.1.1:/share', local_mount_point: '/mnt/share' }])

  await page.route('**/api/jobs', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([createdJob]) })
      return
    }
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(createdJob) })
      return
    }
    await route.fallback()
  })

  await routeJson(page, '**/api/jobs/77', createdJob)
  await routeJson(page, '**/api/jobs/77/files', { files: [{ id: 101, relative_path: 'a.txt', status: 'COMPLETED', checksum: 'abc' }] })
  await routeJson(page, '**/api/jobs/77/start', { ...createdJob, status: 'RUNNING', copied_bytes: 50 })
  await routeJson(page, '**/api/jobs/77/verify', { ...createdJob, status: 'VERIFYING', copied_bytes: 100 })
  await routeJson(page, '**/api/jobs/77/manifest', { ...createdJob, status: 'COMPLETED', copied_bytes: 100 })
  await routeJson(page, '**/api/introspection/jobs/77/debug', { files: [{ id: 101, relative_path: 'a.txt', status: 'COMPLETED', checksum: 'abc' }] })

  await page.goto('/jobs')
  await page.getByRole('button', { name: 'Create Job' }).click()
  await page.getByLabel('Select drive').selectOption('1')
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByLabel('Select mount source').selectOption('4')
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByLabel('Project').fill('P-77')
  await page.getByLabel('Evidence').fill('EV-77')
  await page.getByLabel('Source path').fill('folder')
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByRole('button', { name: 'Create Job' }).click()

  await expect(page).toHaveURL(/\/jobs\/77$/)
  await page.getByRole('button', { name: 'Start' }).click()
  // After starting, the job enters RUNNING state; the progress bar should be visible
  await expect(page.locator('.progress-bar')).toBeVisible()

  await page.getByRole('button', { name: 'Verify' }).click()
  await page.getByRole('button', { name: 'Generate Manifest' }).click()

  await expectNoCriticalA11yViolations(page)
})

test('job detail polls and reflects status progression', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  let pollCount = 0
  const base = { id: 88, project_id: 'P-88', evidence_number: 'EV-88', thread_count: 4, total_bytes: 400 }

  // Register the broad catch-all FIRST so that more-specific handlers registered
  // afterward take precedence (Playwright uses LIFO route priority).
  await routeJson(page, '**/api/jobs**', [{ ...base, copied_bytes: 0, status: 'RUNNING' }])
  await routeJson(page, '**/api/jobs/88/files', { files: [] })
  await routeJson(page, '**/api/introspection/jobs/88/debug', { files: [] })
  await page.route('**/api/jobs/88', async (route) => {
    pollCount += 1
    const copied = Math.min(pollCount * 100, 400)
    const status = copied >= 400 ? 'COMPLETED' : 'RUNNING'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...base, copied_bytes: copied, status }),
    })
  })

  await page.goto('/jobs/88')

  // First render: job is RUNNING
  await expect(page.getByText('RUNNING')).toBeVisible()
  // Progress bar is rendered while in progress
  await expect(page.locator('.progress-bar')).toBeVisible()
  // Polling eventually advances to COMPLETED (polling interval is 3 s; allow up to 20 s)
  await expect(page.getByText('COMPLETED')).toBeVisible({ timeout: 20000 })
})
