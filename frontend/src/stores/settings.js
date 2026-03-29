import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { STORAGE_SETTINGS_KEY } from '@/constants/storage.js'
import { AUDIT_EXPORT_FILENAME } from '@/constants/exports.js'

export const useSettingsStore = defineStore('settings', () => {
  const auditExportFilename = ref(AUDIT_EXPORT_FILENAME)

  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_SETTINGS_KEY)
      if (raw) {
        const data = JSON.parse(raw)
        if (data.auditExportFilename) {
          auditExportFilename.value = data.auditExportFilename
        }
      }
    } catch {
      // ignore corrupt storage
    }
  }

  function persist() {
    localStorage.setItem(
      STORAGE_SETTINGS_KEY,
      JSON.stringify({ auditExportFilename: auditExportFilename.value }),
    )
  }

  watch(auditExportFilename, persist)
  load()

  return { auditExportFilename }
})
