import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { STORAGE_SETTINGS_KEY } from '@/constants/storage.js'
import { AUDIT_EXPORT_FILENAME, DOWNLOAD_REVOKE_DELAY_MS } from '@/constants/exports.js'
import { logger } from '@/utils/logger.js'

export const useSettingsStore = defineStore('settings', () => {
  const auditExportFilename = ref(AUDIT_EXPORT_FILENAME)
  const downloadRevokeDelayMs = ref(DOWNLOAD_REVOKE_DELAY_MS)

  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_SETTINGS_KEY)
      if (raw) {
        const data = JSON.parse(raw)
        if (data.auditExportFilename) {
          auditExportFilename.value = data.auditExportFilename
        }
        if (typeof data.downloadRevokeDelayMs === 'number' && data.downloadRevokeDelayMs > 0) {
          downloadRevokeDelayMs.value = data.downloadRevokeDelayMs
        }
      }
    } catch (err) {
      logger.debug('[settings] corrupt storage, ignoring:', err)
    }
  }

  function persist() {
    localStorage.setItem(
      STORAGE_SETTINGS_KEY,
      JSON.stringify({
        auditExportFilename: auditExportFilename.value,
        downloadRevokeDelayMs: downloadRevokeDelayMs.value,
      }),
    )
  }

  watch([auditExportFilename, downloadRevokeDelayMs], persist)
  load()

  return { auditExportFilename, downloadRevokeDelayMs }
})
