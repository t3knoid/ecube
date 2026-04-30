import { normalizeProjectId } from './projectId.js'

export function buildProjectEvidenceMap(jobs = []) {
  const evidenceByProject = new Map()

  for (const job of jobs) {
    const projectId = normalizeProjectId(job?.project_id)
    const evidenceNumber = typeof job?.evidence_number === 'string' ? job.evidence_number.trim() : ''
    const jobId = Number(job?.id)

    if (!projectId || !evidenceNumber || !Number.isInteger(jobId) || evidenceByProject.has(projectId)) {
      continue
    }

    evidenceByProject.set(projectId, {
      evidenceNumber,
      jobId,
    })
  }

  return evidenceByProject
}

export function getProjectEvidence(projectId, evidenceByProject) {
  const normalizedProjectId = normalizeProjectId(projectId)
  if (!normalizedProjectId || !(evidenceByProject instanceof Map)) {
    return ''
  }

  return evidenceByProject.get(normalizedProjectId)?.evidenceNumber || ''
}

export function getProjectEvidenceJobId(projectId, evidenceByProject) {
  const normalizedProjectId = normalizeProjectId(projectId)
  if (!normalizedProjectId || !(evidenceByProject instanceof Map)) {
    return null
  }

  return evidenceByProject.get(normalizedProjectId)?.jobId ?? null
}

export function buildDriveJobMap(jobs = []) {
  const jobByDrive = new Map()

  for (const job of jobs) {
    const driveId = Number(job?.drive?.id)
    const jobId = Number(job?.id)
    const evidenceNumber = typeof job?.evidence_number === 'string' ? job.evidence_number.trim() : ''

    if (!Number.isInteger(driveId) || !Number.isInteger(jobId) || jobByDrive.has(driveId)) {
      continue
    }

    jobByDrive.set(driveId, {
      jobId,
      evidenceNumber,
    })
  }

  return jobByDrive
}

export function getDriveJob(driveId, jobsByDrive) {
  const normalizedDriveId = Number(driveId)
  if (!Number.isInteger(normalizedDriveId) || !(jobsByDrive instanceof Map)) {
    return null
  }

  return jobsByDrive.get(normalizedDriveId) || null
}