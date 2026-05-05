import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const patch = vi.fn()
const toData = vi.fn((value) => value)

vi.mock('@/api/client.js', () => ({
  default: {
    get: (...args) => get(...args),
    post: (...args) => post(...args),
    patch: (...args) => patch(...args),
  },
}))

vi.mock('@/api/data.js', () => ({
  toData: (...args) => toData(...args),
}))

describe('mounts api helpers', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    patch.mockReset()
    toData.mockClear()
    post.mockResolvedValue({ data: { ok: true } })
    patch.mockResolvedValue({ data: { ok: true } })
  })

  it('forwards an optional timeout override for mount share discovery requests', async () => {
    const { discoverMountShares } = await import('@/api/mounts.js')

    await discoverMountShares({ type: 'SMB', remote_path: '//server' }, { timeout: 75000 })

    expect(post).toHaveBeenCalledWith('/api/mounts/discover', { type: 'SMB', remote_path: '//server' }, expect.objectContaining({ timeout: 75000 }))
    expect(toData).toHaveBeenCalled()
  })

  it('forwards an optional timeout override for mount validation requests', async () => {
    const { validateMountCandidate } = await import('@/api/mounts.js')

    await validateMountCandidate({ type: 'SMB', remote_path: '//server/share', project_id: 'PROJ-1' }, { timeout: 180000 })

    expect(post).toHaveBeenCalledWith('/api/mounts/test', { type: 'SMB', remote_path: '//server/share', project_id: 'PROJ-1' }, expect.objectContaining({ timeout: 180000 }))
    expect(toData).toHaveBeenCalled()
  })

  it('forwards an optional timeout override for mount create and update requests', async () => {
    const { createMount, updateMount } = await import('@/api/mounts.js')

    await createMount({ type: 'SMB', remote_path: '//server/share', project_id: 'PROJ-1' }, { timeout: 180000 })
    await updateMount(11, { type: 'SMB', remote_path: '//server/share', project_id: 'PROJ-1' }, { timeout: 180000 })

    expect(post).toHaveBeenCalledWith('/api/mounts', { type: 'SMB', remote_path: '//server/share', project_id: 'PROJ-1' }, expect.objectContaining({ timeout: 180000 }))
    expect(patch).toHaveBeenCalledWith('/api/mounts/11', { type: 'SMB', remote_path: '//server/share', project_id: 'PROJ-1' }, expect.objectContaining({ timeout: 180000 }))
    expect(toData).toHaveBeenCalled()
  })
})