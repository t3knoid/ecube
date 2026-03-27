import { beforeEach, describe, expect, it, vi } from 'vitest'
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
})
