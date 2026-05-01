import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AUTH_RESET_EVENT, EXPIRED_QUERY_KEY, EXPIRED_QUERY_VALUE } from '@/constants/auth.js'
import { LOGIN_PATH } from '@/constants/routes.js'
import { STORAGE_TOKEN_KEY } from '@/constants/storage.js'

vi.mock('axios', () => {
  const requestHandlers = []
  const responseHandlers = []

  const instance = {
    interceptors: {
      request: {
        use(fn) {
          requestHandlers.push(fn)
        },
      },
      response: {
        use(success, failure) {
          responseHandlers.push({ success, failure })
        },
      },
    },
    _requestHandlers: requestHandlers,
    _responseHandlers: responseHandlers,
  }

  return {
    default: {
      create: vi.fn(() => instance),
    },
  }
})

const warning = vi.fn()
const error = vi.fn()

vi.mock('@/composables/useToast.js', () => ({
  useToast: () => ({ warning, error }),
}))

describe('api/client interceptors', () => {
  beforeEach(() => {
    vi.resetModules()
    sessionStorage.clear()
    warning.mockReset()
    error.mockReset()
    window.location.href = 'http://localhost/'
  })

  it('attaches bearer token from sessionStorage', async () => {
    sessionStorage.setItem(STORAGE_TOKEN_KEY, 'abc123')

    const { default: apiClient } = await import('@/api/client.js')
    const { default: axios } = await import('axios')
    expect(axios.create).toHaveBeenCalledWith(
      expect.objectContaining({ baseURL: '', timeout: 30000 }),
    )

    const requestInterceptor = apiClient._requestHandlers[0]

    const config = { headers: {} }
    const out = requestInterceptor(config)

    expect(out.headers.Authorization).toBe('Bearer abc123')
  })

  it('handles 403 with warning toast', async () => {
    const { default: apiClient } = await import('@/api/client.js')
    const responseInterceptor = apiClient._responseHandlers[0].failure

    await expect(
      responseInterceptor({ response: { status: 403, data: {} } }),
    ).rejects.toBeTruthy()

    expect(warning).toHaveBeenCalledWith(
      'Insufficient permissions. Your role may not allow this action.',
    )
  })

  it('handles 401 by clearing token and dispatching auth reset event', async () => {
    sessionStorage.setItem(STORAGE_TOKEN_KEY, 'abc123')
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

    const { default: apiClient } = await import('@/api/client.js')
    const responseInterceptor = apiClient._responseHandlers[0].failure

    await expect(
      responseInterceptor({ response: { status: 401, data: { detail: 'Token expired' } } }),
    ).rejects.toBeTruthy()

    expect(sessionStorage.getItem(STORAGE_TOKEN_KEY)).toBeNull()
    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({ type: AUTH_RESET_EVENT }))
  })

  it('detects expired session from ErrorResponse.message', async () => {
    const { isExpiredAuthPayload } = await import('@/api/client.js')

    expect(isExpiredAuthPayload({ message: 'Token expired' })).toBe(true)
    expect(isExpiredAuthPayload({ message: 'Unauthorized' })).toBe(false)
  })

  it('detects the backend unauthorized payload shape', async () => {
    const { isUnauthorizedAuthPayload } = await import('@/api/client.js')

    expect(
      isUnauthorizedAuthPayload({
        code: 'UNAUTHORIZED',
        message: 'Missing authentication token',
      }),
    ).toBe(true)
    expect(
      isUnauthorizedAuthPayload({
        code: 'FORBIDDEN',
        message: 'Missing authentication token',
      }),
    ).toBe(false)
  })

  it('redirects to login when backend unauthorized payload is returned outside the 401 branch', async () => {
    sessionStorage.setItem(STORAGE_TOKEN_KEY, 'abc123')
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    const originalLocation = window.location
    delete window.location
    window.location = { href: '' }

    const { default: apiClient } = await import('@/api/client.js')
    const responseInterceptor = apiClient._responseHandlers[0].failure

    await expect(
      responseInterceptor({
        response: {
          status: 403,
          data: {
            code: 'UNAUTHORIZED',
            message: 'Missing authentication token',
            trace_id: 'trace-123',
          },
        },
      }),
    ).rejects.toBeTruthy()

    expect(sessionStorage.getItem(STORAGE_TOKEN_KEY)).toBeNull()
    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({ type: AUTH_RESET_EVENT }))
    expect(window.location.href).toBe(LOGIN_PATH)
    expect(warning).not.toHaveBeenCalled()

    window.location = originalLocation
  })

  it('keeps expired-session redirect behavior for 401 responses', async () => {
    sessionStorage.setItem(STORAGE_TOKEN_KEY, 'abc123')
    const originalLocation = window.location
    delete window.location
    window.location = { href: '' }

    const { default: apiClient } = await import('@/api/client.js')
    const responseInterceptor = apiClient._responseHandlers[0].failure

    await expect(
      responseInterceptor({
        response: {
          status: 401,
          data: {
            message: 'Token expired',
          },
        },
      }),
    ).rejects.toBeTruthy()

    expect(window.location.href).toBe(`${LOGIN_PATH}?${EXPIRED_QUERY_KEY}=${EXPIRED_QUERY_VALUE}`)

    window.location = originalLocation
  })

  it('handles 409 using backend message', async () => {
    const { default: apiClient } = await import('@/api/client.js')
    const responseInterceptor = apiClient._responseHandlers[0].failure

    await expect(
      responseInterceptor({ response: { status: 409, data: { message: 'Conflict details' } } }),
    ).rejects.toBeTruthy()

    expect(warning).toHaveBeenCalledWith('Conflict details')
  })

  it('handles 422 FastAPI validation array', async () => {
    const { default: apiClient } = await import('@/api/client.js')
    const responseInterceptor = apiClient._responseHandlers[0].failure

    await expect(
      responseInterceptor({
        response: {
          status: 422,
          data: {
            detail: [{ loc: ['body', 'username'], msg: 'field required' }],
          },
        },
      }),
    ).rejects.toBeTruthy()

    expect(warning).toHaveBeenCalledWith('body.username: field required')
  })

  it('falls back for 422 when detail array has no usable messages', async () => {
    const { default: apiClient } = await import('@/api/client.js')
    const responseInterceptor = apiClient._responseHandlers[0].failure

    await expect(
      responseInterceptor({
        response: {
          status: 422,
          data: {
            detail: [{ foo: 'bar' }],
          },
        },
      }),
    ).rejects.toBeTruthy()

    expect(warning).toHaveBeenCalledWith('Validation failed. Please review your input.')
  })

  it('handles 5xx with trace id', async () => {
    const { default: apiClient } = await import('@/api/client.js')
    const responseInterceptor = apiClient._responseHandlers[0].failure

    await expect(
      responseInterceptor({
        response: {
          status: 500,
          data: {
            message: 'Server exploded',
            trace_id: 'trace-123',
          },
        },
      }),
    ).rejects.toBeTruthy()

    expect(error).toHaveBeenCalledWith('Server exploded', { traceId: 'trace-123' })
  })

  it('handles missing response with network error toast', async () => {
    const { default: apiClient } = await import('@/api/client.js')
    const responseInterceptor = apiClient._responseHandlers[0].failure

    await expect(responseInterceptor({ message: 'Network Error' })).rejects.toBeTruthy()

    expect(error).toHaveBeenCalledWith(
      'Unable to reach the server. Check your network connection and try again.',
    )
  })
})
