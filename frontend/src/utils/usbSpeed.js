export function formatUsbSpeed(value, fallback = '-') {
  const normalized = String(value ?? '').trim()

  if (!normalized || normalized.toLowerCase() === 'unknown') {
    return fallback
  }

  return /mbps$/i.test(normalized) ? normalized : `${normalized} Mbps`
}