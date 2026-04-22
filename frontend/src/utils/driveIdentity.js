export function formatDriveIdentity(drive) {
  const explicitLabel = String(drive?.display_device_label || '').trim()
  if (explicitLabel) {
    return explicitLabel
  }

  const manufacturer = String(drive?.manufacturer || '').trim()
  const productName = String(drive?.product_name || drive?.product || '').trim()
  const portNumber = drive?.port_number
  const parts = []

  if (manufacturer) {
    parts.push(manufacturer)
  }
  if (productName && !parts.includes(productName)) {
    parts.push(productName)
  }

  if (parts.length > 0 && portNumber != null && portNumber !== '') {
    return `${parts.join(' ')} - Port ${portNumber}`
  }
  if (parts.length > 0) {
    return parts.join(' ')
  }
  return drive?.port_system_path || '-'
}