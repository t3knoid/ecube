import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

test('jobs create, start, compare, and manifest flow', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  let jobState = {
    id: 77,
    project_id: 'P-77',
    evidence_number: 'EV-77',
    status: 'PENDING',
    copied_bytes: 0,
    total_bytes: 100,
    file_count: 1,
    files_succeeded: 0,
    files_failed: 0,
    thread_count: 4,
    source_path: '/mnt/share/existing-folder',
    target_mount_path: '/mnt/ecube/1',
    drive: { id: 1, port_system_path: '2-1', device_identifier: 'USB-001' },
  }

  await routeJson(page, '**/api/drives', [{
    id: 1,
    device_identifier: 'USB-001',
    port_system_path: '2-1',
    serial_number: 'SER-001',
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
    const method = route.request().method()
    const url = route.request().url()

    if (method === 'GET' && /\/api\/jobs(?:\?|$)/.test(url)) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([jobState]) })
      return
    }
    if (method === 'POST' && /\/api\/jobs(?:\?|$)/.test(url)) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
      return
    }
    await route.fallback()
  })

  await page.route('**/api/jobs/77', async (route) => {
    if (route.request().method() === 'PUT') {
      const payload = route.request().postDataJSON()
      jobState = {
        ...jobState,
        ...payload,
        source_path: '/mnt/share/updated-folder',
      }
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })

  await routeJson(page, '**/api/jobs/77/files', {
    total_files: 1,
    returned_files: 1,
    files: [{ id: 101, relative_path: 'a.txt', status: 'COMPLETED', checksum: 'abc' }],
  })
  await routeJson(page, '**/api/introspection/jobs/77/debug', { files: [{ id: 101, relative_path: 'a.txt', status: 'COMPLETED', checksum: 'abc' }] })
  await routeJson(page, '**/api/files/101/hashes', { file_id: 101, relative_path: 'a.txt', md5: 'md5-abc', sha256: 'sha-abc', size_bytes: 12 })
  await page.route('**/api/files/compare', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        match: true,
        hash_match: true,
        size_match: true,
        path_match: true,
        file_a: { file_id: 101, relative_path: 'a.txt', size_bytes: 12, sha256: 'sha-abc' },
        file_b: { file_id: 101, relative_path: 'a.txt', size_bytes: 12, sha256: 'sha-abc' },
      }),
    })
  })
  await page.route('**/api/jobs/77/start', async (route) => {
    jobState = { ...jobState, status: 'COMPLETED', copied_bytes: 100, total_bytes: 100, files_succeeded: 1 }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })
  await page.route('**/api/jobs/77/verify', async (route) => {
    jobState = { ...jobState, status: 'COMPLETED', copied_bytes: 100, total_bytes: 100, files_succeeded: 1 }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })
  await page.route('**/api/jobs/77/manifest', async (route) => {
    jobState = { ...jobState, status: 'COMPLETED', copied_bytes: 100, total_bytes: 100, files_succeeded: 1 }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
  })

  await page.goto('/jobs')
  await expect(page.getByText('Device')).toBeVisible()
  await expect(page.getByText('2-1')).toBeVisible()
  await page.getByRole('button', { name: 'Create Job' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByLabel('Select device')).toBeVisible()
  await page.locator('#job-project').selectOption('P-77')
  await page.locator('#job-evidence').fill('EV-77')
  await page.locator('#job-mount').selectOption('4')
  await page.locator('#job-source-path').fill('folder')
  await page.locator('#job-drive').selectOption('1')
  await expect(page.locator('#job-drive')).toContainText('2-1')
  await expect(page.locator('#job-drive')).not.toContainText('USB-001')
  await page.getByRole('dialog').getByRole('button', { name: 'Create Job' }).click()

  await expect(page).toHaveURL(/\/jobs\/77$/)

  await page.getByRole('button', { name: 'Edit' }).click()
  await expect(page.getByRole('heading', { name: 'Edit Job' })).toBeVisible()
  await expect(page.getByLabel('Select device')).toBeVisible()
  await page.locator('#job-evidence').fill('EV-77-UPDATED')
  await page.locator('#job-mount').selectOption('4')
  await page.locator('#job-drive').selectOption('1')
  await page.locator('#job-source-path').fill('/updated-folder')
  await page.locator('#job-submit').click()
  await expect(page.getByText('EV-77-UPDATED')).toBeVisible()

  await expect(page.getByRole('button', { name: 'Verify' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Generate Manifest' })).toBeDisabled()

  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page.locator('.progress-bar')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Verify' })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Generate Manifest' })).toBeEnabled()

  await expect(page.locator('.status-badge').filter({ hasText: 'COMPLETED' }).first()).toBeVisible()
  await expect(page.getByText('Source / Destination Compare')).toBeVisible()
  await page.getByRole('button', { name: 'View Hashes' }).click()
  await page.locator('#compare-file-source').selectOption('101')
  await page.getByRole('button', { name: 'Compare' }).click()
  await expect(page.getByText('Overall Match')).toBeVisible()
  await expect(page.getByText('Hash Match')).toBeVisible()
  await expect(page.getByText('Path Match')).toBeVisible()

  await page.getByRole('button', { name: 'Generate Manifest' }).click()
  await expect(page.getByText('Manifest generated successfully.')).toBeVisible()
  await expect(page.getByText('/mnt/ecube/1/manifest.json')).toBeVisible()

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
    drive: { id: 9, port_system_path: '2-9', device_identifier: 'USB-009' },
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
  await expect(page.getByText('Device')).toBeVisible()
  await expect(page.getByText('2-9')).toBeVisible()

  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(page.getByText('Pause in progress', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start' })).toBeDisabled()

  await expect(page.getByText('Pause in progress', { exact: true })).toHaveCount(0, { timeout: 10000 })
  await expect(page.getByRole('button', { name: 'Start' })).toBeEnabled({ timeout: 10000 })

  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page.locator('.status-badge').filter({ hasText: 'Running' }).first()).toBeVisible()

  await expectNoCriticalA11yViolations(page)
})

test('jobs surfaces preparing labels during startup analysis', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  await routeJson(page, '**/api/drives', [])
  await routeJson(page, '**/api/mounts', [])
  await routeJson(page, '**/api/jobs**', [{
    id: 92,
    project_id: 'P-92',
    evidence_number: 'EV-92',
    status: 'RUNNING',
    copied_bytes: 0,
    total_bytes: 0,
    file_count: 0,
    files_succeeded: 0,
    files_failed: 0,
    thread_count: 4,
    drive: { id: 9, port_system_path: '2-9', device_identifier: 'USB-009' },
  }])
  await routeJson(page, '**/api/jobs/92', {
    id: 92,
    project_id: 'P-92',
    evidence_number: 'EV-92',
    status: 'RUNNING',
    copied_bytes: 0,
    total_bytes: 0,
    file_count: 0,
    files_succeeded: 0,
    files_failed: 0,
    thread_count: 4,
    source_path: '/nfs/project-092/evidence',
    target_mount_path: '/mnt/ecube/9',
    drive: { id: 9, port_system_path: '2-9', device_identifier: 'USB-009' },
  })
  await routeJson(page, '**/api/jobs/92/files', { files: [] })
  await routeJson(page, '**/api/introspection/jobs/92/debug', { files: [] })

  await page.goto('/jobs')
  await expect(page.getByText('Preparing...', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: 'Details' }).click()
  await expect(page).toHaveURL(/\/jobs\/92$/)
  await expect(page.getByText('Preparing copy...', { exact: true })).toBeVisible()
  await expect(page.getByText('Scanning source files and calculating totals before copy work begins. This can take time for large evidence sets.')).toBeVisible()

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
  await expect(page.locator('.status-badge').filter({ hasText: 'COMPLETED' }).first()).toBeVisible({ timeout: 20000 })
})

test('job detail prefers persisted failure reasons over derived file summaries', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])

  await routeJson(page, '**/api/jobs**', [])
  await routeJson(page, '**/api/jobs/91', {
    id: 91,
    project_id: 'P-91',
    evidence_number: 'EV-91',
    status: 'FAILED',
    copied_bytes: 10,
    total_bytes: 100,
    file_count: 2,
    files_succeeded: 1,
    files_failed: 1,
    thread_count: 4,
    source_path: '/nfs/project-091/evidence',
    target_mount_path: '/mnt/ecube/9',
    completed_at: '2026-04-18T10:22:33Z',
    failure_reason: 'Unexpected copy failure (source: bad.txt, destination: bad.txt)',
    error_summary: '1 file failed: Permission denied (/evidence/bad.txt)',
    failure_log_entry: '2026-04-18T10:22:33+00:00 [ERROR] app.services.copy_engine: JOB_FAILED job_id=91 reason=Unexpected copy failure',
  })
  await routeJson(page, '**/api/jobs/91/files', {
    total_files: 1,
    returned_files: 1,
    files: [{ id: 201, relative_path: 'bad.txt', status: 'ERROR', error_message: 'Permission denied' }],
  })
  await routeJson(page, '**/api/introspection/jobs/91/debug', {
    total_files: 1,
    returned_files: 1,
    files: [{ id: 201, relative_path: 'bad.txt', status: 'ERROR', error_message: 'Permission denied' }],
  })

  await page.goto('/jobs/91')

  const failureSummary = page.locator('.failure-summary')
  await expect(failureSummary).toBeVisible()
  await expect(failureSummary.getByText('Failure reason')).toBeVisible()
  await expect(failureSummary.getByText('Unexpected copy failure (source: bad.txt, destination: bad.txt)')).toBeVisible()
  await expect(failureSummary).not.toContainText('1 file failed: Permission denied (/evidence/bad.txt)')
  await expect(failureSummary.getByText('Related log entry')).toBeVisible()
  await expect(failureSummary.getByText('JOB_FAILED job_id=91')).toBeVisible()

  await expectNoCriticalA11yViolations(page)
})
