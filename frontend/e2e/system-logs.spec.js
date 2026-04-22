import { test, expect } from '@playwright/test'
import { setupAuthenticatedPage, routeJson } from './helpers/app.js'

async function stubSystemLogApis(page) {
  await routeJson(page, '**/api/admin/logs', {
    log_files: [
      { name: 'app.log', size: 64, modified: '2026-04-08T11:59:00Z' },
      { name: 'app.log.1', size: 32, modified: '2026-04-08T11:00:00Z' },
    ],
    total_size: 96,
  })
}

test('admin can select and download a rollover log source from the System page', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await stubSystemLogApis(page)

  const requestedSources = []
  await routeJson(page, '**/api/admin/logs/view', (request) => {
    const url = new URL(request.url())
    const source = url.searchParams.get('source') || 'app.log'
    requestedSources.push(source)

    if (source === 'app.log.1') {
      return {
        source: { source: 'app.log.1', path: 'app.log.1' },
        fetched_at: '2026-04-08T12:00:00Z',
        file_modified_at: '2026-04-08T11:00:00Z',
        lines: [{ content: 'ERROR rotated failure', source_path: 'app.log.1' }],
        returned: 1,
        has_more: false,
        limit: 200,
        offset: 0,
      }
    }

    return {
      source: { source: 'app.log', path: 'app.log' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:59:00Z',
      lines: [{ content: 'INFO current healthy', source_path: 'app.log' }],
      returned: 1,
      has_more: false,
      limit: 200,
      offset: 0,
    }
  })

  await page.route('**/api/admin/logs/app.log.1', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/plain',
      headers: {
        'content-disposition': 'attachment; filename="app.log.1"',
      },
      body: 'ERROR rotated failure\n',
    })
  })

  await page.goto('/system')
  await page.getByRole('button', { name: 'Logs' }).click()

  const sourceSelect = page.locator('#log-source')
  await expect(sourceSelect).toBeVisible()
  await expect(sourceSelect.locator('option')).toHaveCount(2)
  await expect(sourceSelect).toHaveValue('app.log')
  await expect(page.locator('.log-viewer')).toContainText('INFO current healthy')

  await sourceSelect.selectOption('app.log.1')
  await expect(page.locator('.log-viewer')).toContainText('ERROR rotated failure')
  expect(requestedSources).toContain('app.log.1')

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('app.log.1')
})

test('admin can page older and newer log lines by scrolling the log viewer', async ({ page }) => {
  await setupAuthenticatedPage(page, ['admin'])
  await stubSystemLogApis(page)

  const currentLines = Array.from({ length: 40 }, () => ({ content: 'line 200', source_path: 'app.log' }))
  const olderLines = Array.from({ length: 40 }, () => ({ content: 'line 199', source_path: 'app.log' }))

  await routeJson(page, '**/api/admin/logs/view', (request) => {
    const url = new URL(request.url())
    const offset = Number(url.searchParams.get('offset') || '0')

    if (offset === 40) {
      return {
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:01Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: olderLines,
        returned: olderLines.length,
        has_more: false,
        limit: 200,
        offset: 40,
      }
    }

    return {
      source: { source: 'app.log', path: 'app.log' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:59:00Z',
      lines: currentLines,
      returned: currentLines.length,
      has_more: true,
      limit: 200,
      offset: 0,
    }
  })

  await page.goto('/system')
  await page.getByRole('button', { name: 'Logs' }).click()

  const viewer = page.locator('.log-viewer')
  await expect(viewer).toContainText('line 200')

  await viewer.evaluate((element) => {
    element.scrollTop = element.scrollHeight
    element.dispatchEvent(new Event('scroll'))
  })

  await expect(viewer).toContainText('line 199')
  await expect(viewer).not.toContainText('line 200')

  await viewer.evaluate((element) => {
    element.scrollTop = 0
    element.dispatchEvent(new Event('scroll'))
  })

  await expect(viewer).toContainText('line 200')
  await expect(viewer).not.toContainText('line 199')
})