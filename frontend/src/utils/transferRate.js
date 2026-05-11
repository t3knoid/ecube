export function formatTransferRate(value, fallback = '-') {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return fallback
  return `${value.toFixed(1)} MB/s`
}