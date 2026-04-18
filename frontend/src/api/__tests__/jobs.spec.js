import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const toData = vi.fn((value) => value)

vi.mock('@/api/client.js', () => ({
  default: {
    get: (...args) => get(...args),
    post: (...args) => post(...args),
  },
}))

vi.mock('@/api/data.js', () => ({
  toData: (...args) => toData(...args),
}))

describe('jobs api helpers', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    toData.mockClear()
    get.mockResolvedValue({ data: { id: 77, status: 'PENDING' } })
    post.mockResolvedValue({ data: { id: 77, status: 'RUNNING' } })
  })

  it('forwards the start payload to the backend', async () => {
    const { startJob } = await import('@/api/jobs.js')

    await startJob(77, { thread_count: 6 })

    expect(post).toHaveBeenCalledWith('/api/jobs/77/start', { thread_count: 6 })
    expect(toData).toHaveBeenCalled()
  })

  it('sends an empty object when no start payload is provided', async () => {
    const { startJob } = await import('@/api/jobs.js')

    await startJob(78)

    expect(post).toHaveBeenCalledWith('/api/jobs/78/start', {})
  })

  it('rejects an invalid job id before making the request', async () => {
    const { getJob } = await import('@/api/jobs.js')

    expect(() => getJob('not-a-number')).toThrow('Invalid job id')
    expect(get).not.toHaveBeenCalled()
    expect(post).not.toHaveBeenCalled()
  })
})
