import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

function buildQueryParams(params = {}) {
  const query = new URLSearchParams()

  for (const [key, value] of Object.entries(params)) {
    if (value == null) continue
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item != null) {
          query.append(key, String(item))
        }
      }
      continue
    }
    query.append(key, String(value))
  }

  return query
}

function normalizeJobId(jobId) {
  const normalized = Number(jobId)
  if (!Number.isInteger(normalized) || normalized < 1) {
    throw new TypeError('Invalid job id')
  }
  return normalized
}

export function listJobs(params = {}, { timeout } = {}) {
  const config = { params: buildQueryParams(params) }
  if (timeout != null) {
    config.timeout = timeout
  }
  return toData(apiClient.get(`${API_BASE}/jobs`, config))
}

export function createJob(payload) {
  return toData(apiClient.post(`${API_BASE}/jobs`, payload))
}

export function startJob(jobId, payload = {}) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/start`, payload))
}

export function retryFailedJob(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/retry-failed`))
}

export function analyzeJob(jobId, payload = {}) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/analyze`, payload))
}

export function pauseJob(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/pause`))
}

export function updateJob(jobId, payload) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.put(`${API_BASE}/jobs/${id}`, payload))
}

export function completeJob(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/complete`))
}

export function archiveJob(jobId, payload = { confirm: true }) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/archive`, payload))
}

export function deleteJob(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.delete(`${API_BASE}/jobs/${id}`))
}

export function clearJobStartupAnalysisCache(jobId, payload = { confirm: true }) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/startup-analysis/clear`, payload))
}

export function getJob(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.get(`${API_BASE}/jobs/${id}`))
}

export function getJobChainOfCustody(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.get(`${API_BASE}/jobs/${id}/chain-of-custody`))
}

export function refreshJobChainOfCustody(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/chain-of-custody/refresh`))
}

export function confirmJobChainOfCustodyHandoff(jobId, payload) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/chain-of-custody/handoff`, payload))
}

export function getJobFiles(jobId, params = {}) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.get(`${API_BASE}/jobs/${id}/files`, { params }))
}

export function verifyJob(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/verify`))
}

export function generateManifest(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/manifest`))
}

export function downloadManifest(jobId) {
  const id = normalizeJobId(jobId)
  return apiClient.get(`${API_BASE}/jobs/${id}/manifest/download`, {
    responseType: 'blob',
  })
}
