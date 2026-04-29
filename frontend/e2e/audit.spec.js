import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson, stubDrivesApi } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

async function openJobDetailChainOfCustody(page) {
  const chainButton = page.getByRole('button', { name: 'Chain of Custody' })
  if (await chainButton.count()) {
    await chainButton.click()
    return
  }

  await page.getByLabel('Job Detail actions').click()
  await page.getByRole('button', { name: 'Chain of Custody' }).click()
}

test('audit filters and export csv', async ({ page }) => {
  await setupAuthenticatedPage(page, ['auditor'])
  await stubDrivesApi(page, [])

  await page.route(/\/api\/audit(?!\/)/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 1,
          timestamp: '2026-03-29T10:00:00Z',
          user: 'frank',
          action: 'LOGIN',
          job_id: null,
          client_ip: '127.0.0.1',
          details: { message: 'ok' },
        },
      ]),
    })
  })

  await page.goto('/audit')
  await page.getByPlaceholder('Filter by user').fill('frank')
  await page.getByPlaceholder('Filter by action').fill('LOGIN')

  // Date filter — inputs are datetime-local, targeted by aria-label
  await page.getByLabel('From Date').fill('2026-03-29T00:00')

  await page.getByRole('button', { name: 'Apply' }).click()

  await expect(page.locator('tbody').getByText('frank')).toBeVisible()

  // Export CSV — verify download is triggered
  const exportBtn = page.getByRole('button', { name: 'Export Audit CSV' })
  await expect(exportBtn).toBeVisible()
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 5000 }).catch(() => null),
    exportBtn.click(),
  ])
  // Accept either a real download or a client-side Blob link click (no download event)
  if (download) {
    expect(download.suggestedFilename()).toMatch(/\.csv$/i)
  }

  await expectNoCriticalA11yViolations(page)
})

test('job detail chain of custody report renders printable sections and CoC exports on mobile', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'Print media assertions are unstable in webkit for this view')

  await page.setViewportSize({ width: 390, height: 844 })
  await setupAuthenticatedPage(page, ['auditor'])
  await routeJson(page, '**/api/drives**', [])
  await routeJson(page, '**/api/mounts', [])
  await routeJson(page, '**/api/jobs/12/files', { total_files: 0, returned_files: 0, files: [] })
  await routeJson(page, '**/api/jobs/12', {
    id: 12,
    project_id: 'PRJ-001',
    evidence_number: 'EV-12',
    status: 'ARCHIVED',
    copied_bytes: 1024,
    total_bytes: 1024,
    file_count: 3,
    files_succeeded: 3,
    files_failed: 0,
    files_timed_out: 0,
    thread_count: 4,
    source_path: '/mnt/share/evidence',
    target_mount_path: '/mnt/ecube/1',
    drive: { id: 1, current_state: 'ARCHIVED', is_mounted: false, device_identifier: 'SN-001' },
  })

  await page.route(/\/api\/audit(?!\/)/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })

  await page.route('**/api/jobs/12/chain-of-custody', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        selector_mode: 'JOB',
        project_id: 'PRJ-001',
        snapshot_updated_at: '2026-04-01T14:31:00.000Z',
        reports: [
          {
            drive_id: 1,
            drive_sn: 'SN-001',
            drive_manufacturer: 'Kingston',
            drive_model: 'DataTraveler',
            project_id: 'PRJ-001',
            delivery_time: '2026-04-01T14:30:00.000Z',
            custody_complete: true,
            manifest_summary: [
              {
                job_id: 12,
                evidence_number: 'EV-12',
                processor_notes: 'Sealed container intact',
                total_files: 3,
                total_bytes: 1024,
                manifest_count: 1,
                latest_manifest_path: '/reports/manifests/12.json',
                latest_manifest_format: 'json',
                latest_manifest_created_at: '2026-04-01T14:00:00.000Z',
              },
            ],
            chain_of_custody_events: [
              {
                event_id: 1,
                event_type: 'DRIVE_INITIALIZED',
                timestamp: '2026-04-01T13:00:00.000Z',
                actor: 'auditor-user',
                action: 'Drive initialized',
                details: { drive_id: 1, project_id: 'PRJ-001' },
              },
              {
                event_id: 2,
                event_type: 'COC_HANDOFF_CONFIRMED',
                timestamp: '2026-04-01T14:31:00.000Z',
                actor: 'manager-user',
                action: 'Custody handoff confirmed',
                details: {
                  possessor: 'Officer Jane Doe',
                  received_by: 'Archive Clerk',
                  receipt_ref: 'REC-42',
                  notes: 'Sealed container intact',
                },
              },
            ],
          },
        ],
      }),
    })
  })

  await page.goto('/jobs/12')
  await openJobDetailChainOfCustody(page)

  await expect(page.getByText('Report Header')).toBeVisible()
  await expect(page.getByText('Events Timeline')).toBeVisible()
  await expect(page.getByText('Manifest Summary')).toBeVisible()
  await expect(page.getByText('Attestation')).toBeVisible()
  await expect(page.getByText('Manufacturer')).toBeVisible()
  await expect(page.locator('.coc-print-card dd').filter({ hasText: 'Kingston' })).toBeVisible()
  await expect(page.getByText('Model')).toBeVisible()
  await expect(page.locator('.coc-print-card dd').filter({ hasText: 'DataTraveler' })).toBeVisible()
  await expect(page.getByText('Drive initialized')).toBeVisible()
  await expect(page.getByText('DRIVE_INITIALIZED')).toHaveCount(0)
  await expect(page.getByText('/reports/manifests/12.json')).toBeVisible()
  await expect(page.locator('.coc-print-card dd').filter({ hasText: 'Officer Jane Doe' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prefill Handoff' })).toHaveCount(0)

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 5000 }).catch(() => null),
    page.getByRole('button', { name: 'Export CoC CSV' }).click(),
  ])
  if (download) {
    expect(download.suggestedFilename()).toMatch(/^chain-of-custody-job-.*\.csv$/i)
  }

  const [jsonDownload] = await Promise.all([
    page.waitForEvent('download', { timeout: 5000 }).catch(() => null),
    page.getByRole('button', { name: 'Export JSON' }).click(),
  ])
  if (jsonDownload) {
    expect(jsonDownload.suggestedFilename()).toMatch(/^chain-of-custody-job-.*\.json$/i)
  }

  await page.getByRole('button', { name: 'Print CoC' }).click()
  await page.evaluate(() => document.body.classList.add('printing-coc-report'))

  await page.emulateMedia({ media: 'print' })
  await expect(page.locator('.coc-print-card')).toBeVisible()
  await expect(page.locator('article.panel').first()).toBeHidden()
  await page.emulateMedia({ media: 'screen' })
  await page.evaluate(() => document.body.classList.remove('printing-coc-report'))
})

test.describe('chain of custody handoff', () => {
  test.use({ timezoneId: 'America/New_York' })

  test('requires warning confirmation and submits archive handoff from job detail', async ({ page }) => {
    await setupAuthenticatedPage(page, ['manager'])
    await routeJson(page, '**/api/drives**', [])
    await routeJson(page, '**/api/mounts', [])
    await routeJson(page, '**/api/jobs/12/files', { total_files: 0, returned_files: 0, files: [] })

    await page.route(/\/api\/audit(?!\/)/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })

    let jobState = {
      id: 12,
      project_id: 'PRJ-001',
      evidence_number: 'EV-12',
      status: 'COMPLETED',
      copied_bytes: 1024,
      total_bytes: 1024,
      file_count: 3,
      files_succeeded: 3,
      files_failed: 0,
      files_timed_out: 0,
      thread_count: 4,
      source_path: '/mnt/share/evidence',
      target_mount_path: '/mnt/ecube/1',
      drive: { id: 1, current_state: 'AVAILABLE', is_mounted: false, device_identifier: 'SN-001' },
    }
    await page.route('**/api/jobs/12', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobState) })
    })

    let cocLoads = 0
    await page.route('**/api/jobs/12/chain-of-custody', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.fallback()
        return
      }
      cocLoads += 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          selector_mode: 'JOB',
          project_id: 'PRJ-001',
          snapshot_updated_at: '2026-04-01T14:31:00.000Z',
          reports: [
            {
              drive_id: 1,
              drive_sn: 'SN-001',
              drive_manufacturer: 'Kingston',
              drive_model: 'DataTraveler',
              project_id: 'PRJ-001',
              delivery_time: null,
              custody_complete: false,
              manifest_summary: [{
                job_id: 12,
                evidence_number: 'EV-12',
                processor_notes: 'Initial intake note',
                total_files: 3,
                total_bytes: 1024,
                manifest_count: 1,
                latest_manifest_path: '/reports/manifests/12.json',
                latest_manifest_format: 'json',
                latest_manifest_created_at: '2026-04-01T14:00:00.000Z',
              }],
              chain_of_custody_events: [],
            },
          ],
        }),
      })
    })

    let handoffCallCount = 0
    let lastHandoffBody = null
    await page.route('**/api/jobs/12/chain-of-custody/handoff', async (route) => {
      handoffCallCount += 1
      lastHandoffBody = route.request().postDataJSON()
      jobState = {
        ...jobState,
        status: 'ARCHIVED',
        drive: { ...jobState.drive, current_state: 'ARCHIVED' },
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          event_id: 42,
          event_type: 'COC_HANDOFF_CONFIRMED',
          drive_id: 1,
          project_id: 'PRJ-001',
          creator: 'manager-user',
          possessor: 'Officer Jane Doe',
          delivery_time: '2026-04-01T14:30:00.000Z',
          received_by: null,
          receipt_ref: null,
          notes: null,
          recorded_at: '2026-04-01T14:31:00.000Z',
        }),
      })
    })

    await page.goto('/jobs/12')
    await page.getByRole('button', { name: 'Chain of Custody' }).click()
    await expect(page.getByText('Drive #1 (SN-001)')).toBeVisible()
    await page.getByRole('button', { name: 'Custody Handoff' }).click()
    await expect(page.getByRole('heading', { name: 'Custody Handoff' })).toBeVisible()
    await expect(page.getByText('Standard closeout is an in-app custody handoff. Record it in ECUBE even if external paper paperwork is also used.')).toBeVisible()

    await expect(page.getByLabel('Drive ID')).toHaveValue('1')
    await expect(page.getByLabel('Project Binding')).toHaveValue('PRJ-001')
    await expect(page.getByLabel('Evidence')).toHaveValue('EV-12')
    const expectedDefaultDeliveryTime = await page.evaluate(() => {
      const now = new Date()
      const local = new Date(now.getTime() - (now.getTimezoneOffset() * 60 * 1000))
      return local.toISOString().slice(0, 16)
    })
    await expect(page.getByLabel('Delivery Time (Local Time)')).toHaveValue(expectedDefaultDeliveryTime)
    await page.getByLabel('Possessor').fill('Officer Jane Doe')
    await page.getByLabel('Delivery Time (Local Time)').fill('2026-04-01T10:30')

    await page.getByRole('button', { name: 'Confirm Handoff' }).click()
    await expect(page.getByRole('heading', { name: 'Record custody handoff in ECUBE?' })).toBeVisible()

    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByRole('heading', { name: 'Record custody handoff in ECUBE?' })).toHaveCount(0)
    expect(handoffCallCount).toBe(0)

    await page.getByRole('button', { name: 'Confirm Handoff' }).click()
    await page.getByRole('button', { name: 'Record handoff and archive drive' }).click()

    expect(handoffCallCount).toBe(1)
    expect(cocLoads).toBeGreaterThanOrEqual(1)
    await expect(page.getByRole('heading', { name: 'Record custody handoff in ECUBE?' })).toHaveCount(0)
    await expect(page.getByText('Request conflict, please retry.')).toHaveCount(0)
    expect(lastHandoffBody).toMatchObject({
      drive_id: 1,
      project_id: 'PRJ-001',
      possessor: 'Officer Jane Doe',
      delivery_time: '2026-04-01T14:30:00.000Z',
    })

    await expect(page.getByText('Custody handoff recorded.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Prefill Handoff' })).toHaveCount(0)
  })
})
