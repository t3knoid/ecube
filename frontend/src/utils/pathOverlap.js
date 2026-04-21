function normalizePathParts(path) {
  return String(path || '')
    .trim()
    .split('/')
    .filter(Boolean)
}

function joinNormalizedPath(parts, originalPath) {
  const prefix = String(originalPath || '').trim().startsWith('//') ? '//' : '/'
  return `${prefix}${parts.join('/')}`
}

export function resolveMountedSourcePath(sourcePath, mountRoot) {
  const rootParts = normalizePathParts(mountRoot)
  const source = String(sourcePath || '').trim()

  if (!rootParts.length || !source) {
    return ''
  }

  if (source === '/') {
    return joinNormalizedPath(rootParts, mountRoot)
  }

  const sourceParts = normalizePathParts(source)
  return joinNormalizedPath([...rootParts, ...sourceParts], mountRoot)
}

export function classifySourcePathOverlap(existingPath, newPath) {
  const existingParts = normalizePathParts(existingPath)
  const newParts = normalizePathParts(newPath)

  if (!existingParts.length || !newParts.length) {
    return 'none'
  }

  if (existingParts.length === newParts.length) {
    return existingParts.every((part, index) => part === newParts[index]) ? 'exact' : 'none'
  }

  if (
    newParts.length < existingParts.length
    && newParts.every((part, index) => part === existingParts[index])
  ) {
    return 'ancestor'
  }

  if (
    existingParts.length < newParts.length
    && existingParts.every((part, index) => part === newParts[index])
  ) {
    return 'descendant'
  }

  return 'none'
}