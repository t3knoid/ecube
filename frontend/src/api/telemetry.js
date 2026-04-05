import { API_BASE } from '@/constants/routes.js'
import { STORAGE_TOKEN_KEY } from '@/constants/storage.js'

const UI_NAVIGATION_TELEMETRY_PATH = `${API_BASE}/telemetry/ui-navigation`

const ALLOWED_EVENT_TYPES = new Set([
  'UI_NAVIGATION_CLICK',
  'UI_NAVIGATION_REDIRECT',
  'UI_NAVIGATION_COMPLETED',
])

function normalizeField(value, maxLength = 240) {
  if (value === null || value === undefined) {
    return undefined
  }
  const normalized = String(value).trim().replace(/\s+/g, ' ')
  if (!normalized) return undefined
  if (normalized.length <= maxLength) return normalized
  return normalized.slice(0, maxLength)
}

function normalizePath(value) {
  const normalized = normalizeField(value, 512)
  if (!normalized) return undefined

  if (normalized.startsWith('/')) return normalized
  if (normalized === 'same-page-action') return normalized
  return undefined
}

function buildPayload(event) {
  const eventType = normalizeField(event?.event_type, 64)
  if (!eventType || !ALLOWED_EVENT_TYPES.has(eventType)) {
    return null
  }

  const payload = {
    event_type: eventType,
    action: normalizeField(event?.action, 64),
    label: normalizeField(event?.label, 120),
    source: normalizePath(event?.source),
    destination: normalizePath(event?.destination),
    route_name: normalizeField(event?.route_name, 120),
    reason: normalizeField(event?.reason, 120),
  }

  return payload
}

export async function postUiNavigationTelemetry(event) {
  if (typeof window === 'undefined' || typeof fetch !== 'function') {
    return false
  }

  const token = sessionStorage.getItem(STORAGE_TOKEN_KEY)
  if (!token) {
    return false
  }

  const payload = buildPayload(event)
  if (!payload) {
    return false
  }

  if (!payload.source && !payload.destination) {
    return false
  }

  try {
    const response = await fetch(UI_NAVIGATION_TELEMETRY_PATH, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
      keepalive: true,
      credentials: 'same-origin',
    })

    return response.ok
  } catch {
    return false
  }
}
