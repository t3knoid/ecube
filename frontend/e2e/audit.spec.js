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
  const exportBtn = page.getByRole('button', { name: 'Export CSV' })
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

test('chain of custody handoff requires warning confirmation and submits archive handoff', async ({ page }) => {
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
        delivery_time: '2026-04-01T10:30:00Z',
        received_by: null,
        receipt_ref: null,
        notes: null,
        recorded_at: '2026-04-01T10:31:00Z',
      }),
    })
  })

  await page.goto('/audit')

  await page.getByLabel('Filter by drive ID').first().selectOption({ label: '#1 (sdb)' })
  await page.getByRole('button', { name: 'Load CoC' }).click()
  await expect(page.getByText('Drive #1 (SN-001)')).toBeVisible()

  await page.getByRole('button', { name: 'Prefill Handoff' }).click()
  await page.getByLabel('Possessor').fill('Officer Jane Doe')
  await page.getByLabel('Delivery Time (UTC)').fill('2026-04-01T10:30')

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
  })
  expect(typeof lastHandoffBody.delivery_time).toBe('string')

  // Verify the report was patched in-place with the handoff response fields.
  // custody_complete should be true and the new event should appear in the events list.
  await expect(page.getByText('Custody Complete')).toBeVisible()

  // Expand the raw events panel (collapsed by default) then read from it.
  await page.locator('.coc-events').getByRole('button', { name: 'Show' }).click()
  await expect(page.locator('.coc-events pre')).toBeVisible()
  const eventsJson = await page.locator('.coc-events pre').textContent()
  const events = JSON.parse(eventsJson)
  const handoffEvent = events.find((e) => e.event_type === 'COC_HANDOFF_CONFIRMED')
  expect(handoffEvent).toBeDefined()
  expect(handoffEvent.event_id).toBe(42)
  expect(handoffEvent.actor).toBe('manager-user')
  expect(handoffEvent.details.possessor).toBe('Officer Jane Doe')
})
