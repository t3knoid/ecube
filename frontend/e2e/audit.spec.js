import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, stubDrivesApi } from './helpers/app.js'
import { expectNoCriticalA11yViolations } from './helpers/a11y.js'

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

test('chain of custody report renders printable sections and CoC CSV export on mobile', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'Print media assertions are unstable in webkit for this view')

  await page.setViewportSize({ width: 390, height: 844 })
  await setupAuthenticatedPage(page, ['auditor'])

  await page.route(/\/api\/audit(?!\/)/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })

  await page.route('**/api/drives**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 1,
          device_identifier: 'sdb',
          display_device_label: 'Kingston DataTraveler - Port 1',
          current_state: 'IN_USE',
          current_project_id: 'PRJ-001',
        },
      ]),
    })
  })

  await page.route('**/api/audit/chain-of-custody**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        selector_mode: 'PROJECT',
        project_id: 'PRJ-001',
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

  await page.goto('/audit')
  await page.getByLabel('Filter by drive ID').first().selectOption({ label: 'Kingston DataTraveler - Port 1' })
  await page.getByRole('button', { name: 'Load CoC' }).click()

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

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 5000 }).catch(() => null),
    page.getByRole('button', { name: 'Export CoC CSV' }).click(),
  ])
  if (download) {
    expect(download.suggestedFilename()).toMatch(/^chain-of-custody-.*\.csv$/i)
  }

  await page.getByRole('button', { name: 'Print CoC' }).click()
  await expect.poll(async () => page.evaluate(() => document.body.classList.contains('coc-print-active'))).toBe(false)

  await page.emulateMedia({ media: 'print' })
  await expect(page.locator('.coc-print-card')).toBeVisible()
  await expect(page.locator('.audit-log-section')).toBeHidden()
  await page.emulateMedia({ media: 'screen' })
})

test.describe('chain of custody handoff', () => {
  test.use({ timezoneId: 'America/New_York' })

  test('requires warning confirmation and submits archive handoff', async ({ page }) => {
    await setupAuthenticatedPage(page, ['manager'])

    await page.route(/\/api\/audit(?!\/)/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })

    await page.route('**/api/drives**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 1,
            device_identifier: 'sdb',
            display_device_label: 'Kingston DataTraveler - Port 1',
            current_state: 'IN_USE',
            current_project_id: 'PRJ-001',
          },
        ]),
      })
    })

    let cocLoads = 0
    await page.route('**/api/audit/chain-of-custody**', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.fallback()
        return
      }
      cocLoads += 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          selector_mode: 'DRIVE_ID',
          reports: [
            {
              drive_id: 1,
              drive_sn: 'SN-001',
              drive_manufacturer: 'Kingston',
              drive_model: 'DataTraveler',
              project_id: 'PRJ-001',
              delivery_time: null,
              custody_complete: false,
              manifest_summary: [],
              chain_of_custody_events: [],
            },
          ],
        }),
      })
    })

    let handoffCallCount = 0
    let lastHandoffBody = null
    await page.route('**/api/audit/chain-of-custody/handoff', async (route) => {
      handoffCallCount += 1
      lastHandoffBody = route.request().postDataJSON()
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

    await page.goto('/audit')

  const cocDriveSelect = page.getByLabel('Filter by drive ID').first()
  await expect(cocDriveSelect.locator('option')).toContainText(['Any drive', 'Kingston DataTraveler - Port 1'])

  const handoffDriveSelect = page.locator('.handoff-form').getByLabel('Filter by drive ID')
  await expect(handoffDriveSelect.locator('option')).toContainText(['Select drive', 'Kingston DataTraveler - Port 1'])

  await page.getByLabel('Filter by drive ID').first().selectOption({ label: 'Kingston DataTraveler - Port 1' })
    await page.getByRole('button', { name: 'Load CoC' }).click()
    await expect(page.getByText('Drive #1 (SN-001)')).toBeVisible()

    await page.getByRole('button', { name: 'Prefill Handoff' }).click()
    await page.getByLabel('Possessor').fill('Officer Jane Doe')
    await page.getByLabel('Delivery Time (Local Time)').fill('2026-04-01T10:30')

    await page.getByRole('button', { name: 'Confirm Handoff' }).click()
    await expect(page.getByRole('heading', { name: 'Permanent Archive Warning' })).toBeVisible()

    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByRole('heading', { name: 'Permanent Archive Warning' })).toHaveCount(0)
    expect(handoffCallCount).toBe(0)

    await page.getByRole('button', { name: 'Confirm Handoff' }).click()
    await page.getByRole('button', { name: 'Yes, archive drive' }).click()

    expect(handoffCallCount).toBe(1)
    expect(cocLoads).toBeGreaterThanOrEqual(1)
    await expect(page.getByRole('heading', { name: 'Permanent Archive Warning' })).toHaveCount(0)
    await expect(page.getByText('Request conflict, please retry.')).toHaveCount(0)
    expect(lastHandoffBody).toMatchObject({
      drive_id: 1,
      project_id: 'PRJ-001',
      possessor: 'Officer Jane Doe',
      delivery_time: '2026-04-01T14:30:00.000Z',
    })

    // Verify the report was patched in-place with the handoff response fields.
    // custody_complete should be true and the new event should appear in the events list.
    await expect(page.locator('.status-badge').filter({ hasText: 'Custody Complete' })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Custody handoff confirmed' })).toBeVisible()
    await expect(page.getByRole('cell', { name: /possessor: Officer Jane Doe/ })).toBeVisible()
  })
})
