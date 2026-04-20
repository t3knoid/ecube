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

  await routeJson(page, '**/api/drives', [{
    id: 1,
    device_identifier: 'USB-001',
    current_state: 'AVAILABLE',
    current_project_id: 'P-77',
    mount_path: '/mnt/ecube/1',
  }])
  await routeJson(page, '**/api/mounts', [{
    id: 4,
    project_id: 'P-77',
    status: 'MOUNTED',
    remote_path: '10.1.1.1:/share',
    local_mount_point: '/mnt/share',
  }])

  await page.route('**/api/jobs**', async (route) => {
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

  let jobState = { ...createdJob }
  await page.route('**/api/jobs/77', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })
  await routeJson(page, '**/api/jobs/77/files', { files: [{ id: 101, relative_path: 'a.txt', status: 'COMPLETED', checksum: 'abc' }] })
  await page.route('**/api/jobs/77/start', async (route) => {
    jobState = { ...jobState, status: 'RUNNING', copied_bytes: 50 }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })
  await page.route('**/api/jobs/77/verify', async (route) => {
    jobState = { ...jobState, status: 'VERIFYING', copied_bytes: 100 }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })
  await page.route('**/api/jobs/77/manifest', async (route) => {
    jobState = { ...jobState, status: 'COMPLETED', copied_bytes: 100 }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })
  await routeJson(page, '**/api/introspection/jobs/77/debug', { files: [{ id: 101, relative_path: 'a.txt', status: 'COMPLETED', checksum: 'abc' }] })

  await page.goto('/jobs')
  await page.getByRole('button', { name: 'Create Job' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.locator('#job-project').selectOption('P-77')
  await page.locator('#job-evidence').fill('EV-77')
  await page.locator('#job-mount').selectOption('4')
  await page.locator('#job-source-path').fill('folder')
  await page.locator('#job-drive').selectOption('1')
  await page.getByRole('dialog').getByRole('button', { name: 'Create Job' }).click()

  await expect(page).toHaveURL(/\/jobs\/77$/)
  await page.getByRole('button', { name: 'Start' }).click()
  // After starting, the job enters RUNNING state; the progress bar should be visible
  await expect(page.locator('.progress-bar')).toBeVisible()

  await page.getByRole('button', { name: 'Verify' }).click()
  await page.getByRole('button', { name: 'Generate Manifest' }).click()

  await expectNoCriticalA11yViolations(page)
})

test('jobs list supports safe pause and resume flow', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  let listCalls = 0
  let jobState = {
    id: 89,
    project_id: 'P-89',
    evidence_number: 'EV-89',
    status: 'RUNNING',
    copied_bytes: 50,
    total_bytes: 100,
    thread_count: 2,
    file_count: 2,
    files_succeeded: 1,
    active_duration_seconds: 90,
  }

  await routeJson(page, '**/api/drives', [])
  await routeJson(page, '**/api/mounts', [])

  await page.route('**/api/jobs**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback()
      return
    }

    listCalls += 1
    if (jobState.status === 'PAUSING' && listCalls >= 3) {
      jobState = { ...jobState, status: 'PAUSED' }
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([jobState]),
    })
  })

  await page.route('**/api/jobs/89/pause', async (route) => {
    jobState = { ...jobState, status: 'PAUSING' }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })

  await page.route('**/api/jobs/89/start', async (route) => {
    jobState = { ...jobState, status: 'RUNNING' }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })

  await page.goto('/jobs')

  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(page.getByText('Pause in progress', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start' })).toBeDisabled()

  await expect(page.getByText('Pause in progress', { exact: true })).toHaveCount(0, { timeout: 10000 })
  await expect(page.getByRole('button', { name: 'Start' })).toBeEnabled({ timeout: 10000 })

  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page.locator('.status-badge').filter({ hasText: 'Running' }).first()).toBeVisible()

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
  await expect(page.getByText('COMPLETED', { exact: true })).toBeVisible({ timeout: 20000 })
})
