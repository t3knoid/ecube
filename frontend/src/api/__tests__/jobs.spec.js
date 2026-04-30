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

  it('serializes repeated job status filters without bracket suffixes', async () => {
    const { listJobs } = await import('@/api/jobs.js')

    await listJobs({
      limit: 1000,
      drive_id: 1,
      statuses: ['PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'VERIFYING'],
    })

    expect(get).toHaveBeenCalledTimes(1)
    const [, config] = get.mock.calls[0]
    expect(config.params).toBeInstanceOf(URLSearchParams)
    expect(config.params.toString()).toBe(
      'limit=1000&drive_id=1&statuses=PENDING&statuses=RUNNING&statuses=PAUSING&statuses=PAUSED&statuses=VERIFYING',
    )
    expect(toData).toHaveBeenCalled()
  })

  it('forwards an optional timeout override for list requests', async () => {
    const { listJobs } = await import('@/api/jobs.js')

    await listJobs({ drive_id: 7, statuses: ['RUNNING'] }, { timeout: 5000 })

    expect(get).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenCalledWith('/api/jobs', expect.objectContaining({ timeout: 5000 }))
  })

  it('paginates through all job pages when callers need more than 1000 rows', async () => {
    toData.mockImplementation(async (value) => (await value).data)
    get
      .mockResolvedValueOnce({ data: Array.from({ length: 1000 }, (_value, index) => ({ id: index + 1 })) })
      .mockResolvedValueOnce({ data: [{ id: 1001 }, { id: 1002 }] })

    const { listAllJobs } = await import('@/api/jobs.js')

    const jobs = await listAllJobs({ include_archived: true })

    expect(get).toHaveBeenNthCalledWith(1, '/api/jobs', expect.objectContaining({
      params: expect.any(URLSearchParams),
    }))
    expect(get.mock.calls[0][1].params.toString()).toBe('include_archived=true&limit=1000&offset=0')
    expect(get.mock.calls[1][1].params.toString()).toBe('include_archived=true&limit=1000&offset=1000')
    expect(jobs).toHaveLength(1002)
    expect(jobs[0]).toEqual({ id: 1 })
    expect(jobs[999]).toEqual({ id: 1000 })
    expect(jobs[1001]).toEqual({ id: 1002 })
  })
})
