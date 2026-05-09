import { beforeEach, describe, expect, it, vi } from 'vitest'

const post = vi.fn()

vi.mock('@/api/client.js', () => ({
  default: {
    post,
  },
}))

describe('postUiNavigationTelemetry', () => {
  beforeEach(() => {
    vi.resetModules()
    post.mockReset()
    sessionStorage.clear()
  })

  it('uses the centralized API client for valid telemetry payloads', async () => {
    sessionStorage.setItem('ecube_token', 'abc123')
    post.mockResolvedValue({ status: 204 })

    const { postUiNavigationTelemetry } = await import('@/api/telemetry.js')

    await expect(
      postUiNavigationTelemetry({
        event_type: 'UI_NAVIGATION_CLICK',
        action: 'a',
        label: 'Open job',
        source: '/jobs',
        destination: '/jobs/1',
      }),
    ).resolves.toBe(true)

    expect(post).toHaveBeenCalledWith(
      '/api/telemetry/ui-navigation',
      {
        event_type: 'UI_NAVIGATION_CLICK',
        action: 'a',
        label: 'Open job',
        source: '/jobs',
        destination: '/jobs/1',
        route_name: undefined,
        reason: undefined,
      },
      {
        adapter: 'fetch',
        keepalive: true,
        credentials: 'same-origin',
      },
    )
  })

  it('returns false without calling the API client when no token is present', async () => {
    const { postUiNavigationTelemetry } = await import('@/api/telemetry.js')

    await expect(
      postUiNavigationTelemetry({
        event_type: 'UI_NAVIGATION_CLICK',
        source: '/jobs',
        destination: '/jobs/1',
      }),
    ).resolves.toBe(false)

    expect(post).not.toHaveBeenCalled()
  })

  it('returns false when the API client rejects the telemetry request', async () => {
    sessionStorage.setItem('ecube_token', 'abc123')
    post.mockRejectedValue(new Error('network'))

    const { postUiNavigationTelemetry } = await import('@/api/telemetry.js')

    await expect(
      postUiNavigationTelemetry({
        event_type: 'UI_NAVIGATION_COMPLETED',
        source: '/jobs',
        destination: '/jobs/1',
        route_name: 'job-detail',
      }),
    ).resolves.toBe(false)
  })
})