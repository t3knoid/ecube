import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCopyTuningDefaultsStore, FALLBACK_COPY_TUNING_DEFAULTS } from '@/stores/copyTuningDefaults.js'

const apiMocks = vi.hoisted(() => ({
  getCopyTuningDefaults: vi.fn(),
}))

const loggerMocks = vi.hoisted(() => ({
  warn: vi.fn(),
  debug: vi.fn(),
}))

vi.mock('@/api/jobs.js', () => ({
  getCopyTuningDefaults: (...args) => apiMocks.getCopyTuningDefaults(...args),
}))

vi.mock('@/utils/logger.js', () => ({
  logger: {
    warn: (...args) => loggerMocks.warn(...args),
    debug: (...args) => loggerMocks.debug(...args),
  },
}))

describe('copyTuningDefaults store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMocks.getCopyTuningDefaults.mockReset()
    loggerMocks.warn.mockReset()
    loggerMocks.debug.mockReset()
  })

  it('loads and marks defaults as loaded for a valid payload', async () => {
    apiMocks.getCopyTuningDefaults.mockResolvedValue({
      thread_count: 8,
      copy_chunk_size_bytes: 4_194_304,
      copy_progress_flush_bytes: 67_108_864,
      copy_file_fsync_enabled: true,
    })

    const store = useCopyTuningDefaultsStore()
    await store.ensureLoaded()

    expect(store.loaded).toBe(true)
    expect(store.currentDefaults()).toEqual({
      thread_count: 8,
      copy_chunk_size_bytes: 4_194_304,
      copy_progress_flush_bytes: 67_108_864,
      copy_file_fsync_enabled: true,
    })
    expect(loggerMocks.warn).not.toHaveBeenCalled()
  })

  it('keeps fallback defaults and remains unloaded for an invalid payload', async () => {
    apiMocks.getCopyTuningDefaults.mockResolvedValue({
      thread_count: 8,
      copy_chunk_size_bytes: 4_194_304,
      copy_progress_flush_bytes: 67_108_864,
      copy_file_fsync_enabled: 'false',
    })

    const store = useCopyTuningDefaultsStore()
    await store.ensureLoaded()

    expect(store.loaded).toBe(false)
    expect(store.currentDefaults()).toEqual(FALLBACK_COPY_TUNING_DEFAULTS)
    expect(loggerMocks.warn).toHaveBeenCalledWith(
      '[copyTuningDefaults] using hardcoded fallback defaults; backend defaults payload was invalid',
    )
    expect(loggerMocks.debug).toHaveBeenCalledWith(
      '[copyTuningDefaults] invalid backend defaults payload:',
      expect.any(Object),
    )
  })

  it('retries after an invalid payload on the next ensureLoaded call', async () => {
    const store = useCopyTuningDefaultsStore()

    apiMocks.getCopyTuningDefaults.mockResolvedValueOnce({
      thread_count: 0,
      copy_chunk_size_bytes: 4_194_304,
      copy_progress_flush_bytes: 67_108_864,
      copy_file_fsync_enabled: false,
    })
    apiMocks.getCopyTuningDefaults.mockResolvedValueOnce({
      thread_count: 10,
      copy_chunk_size_bytes: 8_388_608,
      copy_progress_flush_bytes: 67_108_864,
      copy_file_fsync_enabled: false,
    })

    await store.ensureLoaded()
    expect(store.loaded).toBe(false)

    await store.ensureLoaded()
    expect(store.loaded).toBe(true)
    expect(store.currentDefaults()).toEqual({
      thread_count: 10,
      copy_chunk_size_bytes: 8_388_608,
      copy_progress_flush_bytes: 67_108_864,
      copy_file_fsync_enabled: false,
    })
    expect(apiMocks.getCopyTuningDefaults).toHaveBeenCalledTimes(2)
  })
})
