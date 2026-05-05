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

describe('drives api helpers', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    toData.mockClear()
    post.mockResolvedValue({ data: { id: 7 } })
  })

  it('forwards an optional timeout override for format requests', async () => {
    const { formatDrive } = await import('@/api/drives.js')

    await formatDrive(7, { filesystem_type: 'ext4' }, { timeout: 0 })

    expect(post).toHaveBeenCalledWith('/api/drives/7/format', { filesystem_type: 'ext4' }, expect.objectContaining({ timeout: 0 }))
    expect(toData).toHaveBeenCalled()
  })

  it('forwards an optional timeout override for mount requests', async () => {
    const { mountDrive } = await import('@/api/drives.js')

    await mountDrive(7, { timeout: 0 })

    expect(post).toHaveBeenCalledWith('/api/drives/7/mount', null, expect.objectContaining({ timeout: 0 }))
    expect(toData).toHaveBeenCalled()
  })
})