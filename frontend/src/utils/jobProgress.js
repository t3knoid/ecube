function clampPercent(value) {
  return Math.max(0, Math.min(100, Math.round(value)))
}

function isActiveStatus(status) {
  return ['RUNNING', 'PAUSING', 'VERIFYING'].includes(String(status || '').toUpperCase())
}

export function calculateJobProgress(job) {
  if (!job) {
    return {
      percent: 0,
      totalBytes: 0,
      copiedBytes: 0,
      totalFiles: 0,
      finishedFiles: 0,
      bytePercent: null,
      filePercent: null,
      active: false,
      initializing: false,
    }
  }

  const status = String(job.status || '').toUpperCase()
  const totalBytes = Number(job.total_bytes || 0)
  const copiedBytes = Number(job.copied_bytes || 0)
  const totalFiles = Number(job.file_count || 0)
  const filesSucceeded = Number(job.files_succeeded || 0)
  const filesFailed = Number(job.files_failed || 0)
  const finishedFiles = Math.min(totalFiles, filesSucceeded + filesFailed)
  const active = isActiveStatus(status)

  const bytePercent = totalBytes > 0
    ? clampPercent((copiedBytes / totalBytes) * 100)
    : null
  const filePercent = totalFiles > 0
    ? clampPercent((finishedFiles / totalFiles) * 100)
    : null

  const knownPercents = [bytePercent, filePercent].filter((value) => value != null)
  const percent = active
    ? (knownPercents.length ? Math.min(...knownPercents) : 0)
    : (bytePercent ?? filePercent ?? 0)
  const initializing = active && totalBytes === 0 && totalFiles === 0 && copiedBytes === 0 && finishedFiles === 0

  const displayCopiedBytes = active && totalBytes > 0 && bytePercent != null && bytePercent > percent
    ? Math.min(copiedBytes, Math.floor((percent / 100) * totalBytes))
    : copiedBytes

  return {
    percent,
    totalBytes,
    copiedBytes: displayCopiedBytes,
    totalFiles,
    finishedFiles,
    bytePercent,
    filePercent,
    active,
    initializing,
  }
}

export function isJobProgressActive(job) {
  return isActiveStatus(job?.status)
}