import { normalizeProjectId } from './projectId.js'

export function buildProjectEvidenceMap(jobs = []) {
  const evidenceByProject = new Map()

  for (const job of jobs) {
    const projectId = normalizeProjectId(job?.project_id)
    const evidenceNumber = typeof job?.evidence_number === 'string' ? job.evidence_number.trim() : ''

    if (!projectId || !evidenceNumber || evidenceByProject.has(projectId)) {
      continue
    }

    evidenceByProject.set(projectId, evidenceNumber)
  }

  return evidenceByProject
}

export function getProjectEvidence(projectId, evidenceByProject) {
  const normalizedProjectId = normalizeProjectId(projectId)
  if (!normalizedProjectId || !(evidenceByProject instanceof Map)) {
    return ''
  }

  return evidenceByProject.get(normalizedProjectId) || ''
}