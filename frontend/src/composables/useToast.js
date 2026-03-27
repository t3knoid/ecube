import { ref } from 'vue'

let _nextId = 0

const toasts = ref([])

const DEFAULT_DURATIONS = {
  success: 4000,
  info: 4000,
  warning: 6000,
  error: 8000,
}

function addToast({ type = 'info', message, traceId = null, duration = null }) {
  const id = ++_nextId
  const ms = duration ?? DEFAULT_DURATIONS[type] ?? 4000
  const toast = { id, type, message, traceId, duration: ms }
  toasts.value.push(toast)

  if (ms > 0) {
    setTimeout(() => removeToast(id), ms)
  }
  return id
}

function removeToast(id) {
  const idx = toasts.value.findIndex((t) => t.id === id)
  if (idx !== -1) {
    toasts.value.splice(idx, 1)
  }
}

function success(message, opts = {}) {
  return addToast({ type: 'success', message, ...opts })
}

function info(message, opts = {}) {
  return addToast({ type: 'info', message, ...opts })
}

function warning(message, opts = {}) {
  return addToast({ type: 'warning', message, ...opts })
}

function error(message, opts = {}) {
  return addToast({ type: 'error', message, ...opts })
}

export function useToast() {
  return { toasts, addToast, removeToast, success, info, warning, error }
}
