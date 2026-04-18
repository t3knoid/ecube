export function normalizeProjectId(value) {
  if (typeof value !== 'string') return ''
  return value.trim().toUpperCase()
}

export function normalizeProjectRecord(record, keys = ['project_id', 'current_project_id']) {
  if (!record || typeof record !== 'object') return record

  const next = { ...record }
  for (const key of keys) {
    if (typeof next[key] === 'string') {
      const normalized = normalizeProjectId(next[key])
      next[key] = normalized || null
    }
  }
  return next
}
