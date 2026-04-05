import { beforeEach, describe, expect, it, vi } from 'vitest'

const debug = vi.fn()
const postUiNavigationTelemetry = vi.fn()

vi.mock('@/utils/logger.js', () => ({
  logger: { debug },
}))

vi.mock('@/api/telemetry.js', () => ({
  postUiNavigationTelemetry,
}))

describe('installNavigationTracing', () => {
  beforeEach(() => {
    vi.resetModules()
    debug.mockReset()
    postUiNavigationTelemetry.mockReset()
    postUiNavigationTelemetry.mockResolvedValue(true)
    document.body.innerHTML = ''
    window.history.pushState({}, '', '/jobs')
  })

  it('posts telemetry for internal navigation clicks', async () => {
    const afterEachHandlers = []
    const router = {
      resolve: vi.fn((destination) => ({ fullPath: destination })),
      afterEach: vi.fn((handler) => {
        afterEachHandlers.push(handler)
        return vi.fn()
      }),
    }

    const { installNavigationTracing } = await import('@/utils/navigationTrace.js')
    const stop = installNavigationTracing(router)

    const link = document.createElement('a')
    link.setAttribute('href', '/jobs/1')
    link.textContent = 'Open job'
    document.body.appendChild(link)

    link.dispatchEvent(new MouseEvent('click', { bubbles: true }))

    expect(debug).toHaveBeenCalledWith('UI_NAVIGATION_CLICK', {
      action: 'a',
      label: 'Open job',
      from: '/jobs',
      to: '/jobs/1',
    })
    expect(postUiNavigationTelemetry).toHaveBeenCalledWith({
      event_type: 'UI_NAVIGATION_CLICK',
      action: 'a',
      label: 'Open job',
      source: '/jobs',
      destination: '/jobs/1',
    })

    stop()
  })

  it('ignores same-page actions and external links', async () => {
    const router = {
      resolve: vi.fn((destination) => ({ fullPath: destination })),
      afterEach: vi.fn(() => vi.fn()),
    }

    const { installNavigationTracing } = await import('@/utils/navigationTrace.js')
    const stop = installNavigationTracing(router)

    const button = document.createElement('button')
    button.textContent = 'Refresh'
    document.body.appendChild(button)

    button.dispatchEvent(new MouseEvent('click', { bubbles: true }))

    const externalLink = document.createElement('a')
    externalLink.setAttribute('href', 'https://example.com/docs')
    externalLink.textContent = 'Docs'
    document.body.appendChild(externalLink)

    externalLink.dispatchEvent(new MouseEvent('click', { bubbles: true }))

    expect(debug).not.toHaveBeenCalledWith(
      'UI_NAVIGATION_CLICK',
      expect.anything(),
    )
    expect(postUiNavigationTelemetry).not.toHaveBeenCalled()

    stop()
  })

  it('posts telemetry for completed route navigation', async () => {
    const afterEachHandlers = []
    const stopAfterEach = vi.fn()
    const router = {
      resolve: vi.fn((destination) => ({ fullPath: destination })),
      afterEach: vi.fn((handler) => {
        afterEachHandlers.push(handler)
        return stopAfterEach
      }),
    }

    const { installNavigationTracing } = await import('@/utils/navigationTrace.js')
    const stop = installNavigationTracing(router)

    afterEachHandlers[0](
      { fullPath: '/jobs/1', name: 'job-detail' },
      { fullPath: '/jobs', name: 'jobs' },
      undefined,
    )

    expect(debug).toHaveBeenCalledWith('UI_NAVIGATION_COMPLETED', {
      from: '/jobs',
      to: '/jobs/1',
      route_name: 'job-detail',
    })
    expect(postUiNavigationTelemetry).toHaveBeenCalledWith({
      event_type: 'UI_NAVIGATION_COMPLETED',
      source: '/jobs',
      destination: '/jobs/1',
      route_name: 'job-detail',
    })

    stop()
    expect(stopAfterEach).toHaveBeenCalled()
  })
})