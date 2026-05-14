import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getCopyTuningDefaults } from '@/api/jobs.js'
import { logger } from '@/utils/logger.js'

// Hardcoded last-resort fallbacks. These mirror the backend Pydantic
// defaults defined in ``app/config.py`` and are only used when the
// configured values cannot be loaded from the backend.
export const FALLBACK_COPY_TUNING_DEFAULTS = Object.freeze({
  thread_count: 12,
  copy_chunk_size_bytes: 4_194_304,
  copy_progress_flush_bytes: 67_108_864,
  copy_file_fsync_enabled: false,
})

export const useCopyTuningDefaultsStore = defineStore('copyTuningDefaults', () => {
  const threadCount = ref(FALLBACK_COPY_TUNING_DEFAULTS.thread_count)
  const copyChunkSizeBytes = ref(FALLBACK_COPY_TUNING_DEFAULTS.copy_chunk_size_bytes)
  const copyProgressFlushBytes = ref(FALLBACK_COPY_TUNING_DEFAULTS.copy_progress_flush_bytes)
  const copyFileFsyncEnabled = ref(FALLBACK_COPY_TUNING_DEFAULTS.copy_file_fsync_enabled)
  const loaded = ref(false)
  const loading = ref(false)
  let inflight = null

  function applyDefaults(payload) {
    if (!payload || typeof payload !== 'object') return
    if (Number.isInteger(payload.thread_count) && payload.thread_count >= 1) {
      threadCount.value = payload.thread_count
    }
    if (Number.isInteger(payload.copy_chunk_size_bytes) && payload.copy_chunk_size_bytes >= 1) {
      copyChunkSizeBytes.value = payload.copy_chunk_size_bytes
    }
    if (Number.isInteger(payload.copy_progress_flush_bytes) && payload.copy_progress_flush_bytes >= 1) {
      copyProgressFlushBytes.value = payload.copy_progress_flush_bytes
    }
    if (typeof payload.copy_file_fsync_enabled === 'boolean') {
      copyFileFsyncEnabled.value = payload.copy_file_fsync_enabled
    }
  }

  async function refresh() {
    loading.value = true
    try {
      const data = await getCopyTuningDefaults()
      applyDefaults(data)
      loaded.value = true
    } catch (err) {
      // The Job Editor falls back to FALLBACK_COPY_TUNING_DEFAULTS when the
      // backend defaults cannot be loaded. Surface this at warn level so an
      // operator-visible drift between the dialog seed and the live
      // Configuration values is at least observable in the browser logs;
      // include the raw error at debug level for troubleshooting.
      logger.warn(
        '[copyTuningDefaults] using hardcoded fallback defaults; backend defaults could not be loaded',
      )
      logger.debug('[copyTuningDefaults] failed to load configured defaults:', err)
    } finally {
      loading.value = false
    }
  }

  function ensureLoaded() {
    if (loaded.value) return Promise.resolve()
    if (inflight) return inflight
    inflight = refresh().finally(() => {
      inflight = null
    })
    return inflight
  }

  function reset() {
    threadCount.value = FALLBACK_COPY_TUNING_DEFAULTS.thread_count
    copyChunkSizeBytes.value = FALLBACK_COPY_TUNING_DEFAULTS.copy_chunk_size_bytes
    copyProgressFlushBytes.value = FALLBACK_COPY_TUNING_DEFAULTS.copy_progress_flush_bytes
    copyFileFsyncEnabled.value = FALLBACK_COPY_TUNING_DEFAULTS.copy_file_fsync_enabled
    loaded.value = false
    loading.value = false
    inflight = null
  }

  // Snapshot the current defaults into a plain object suitable for seeding
  // a Job Editor form. Keeping this on the store keeps the Create and Edit
  // surfaces in sync without each view re-listing the four field names.
  function currentDefaults() {
    return {
      thread_count: threadCount.value,
      copy_chunk_size_bytes: copyChunkSizeBytes.value,
      copy_progress_flush_bytes: copyProgressFlushBytes.value,
      copy_file_fsync_enabled: copyFileFsyncEnabled.value,
    }
  }

  return {
    threadCount,
    copyChunkSizeBytes,
    copyProgressFlushBytes,
    copyFileFsyncEnabled,
    loaded,
    loading,
    ensureLoaded,
    refresh,
    reset,
    currentDefaults,
  }
})
