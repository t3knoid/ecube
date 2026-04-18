import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

function normalizeJobId(jobId) {
  const normalized = Number(jobId)
  if (!Number.isInteger(normalized) || normalized < 1) {
    throw new TypeError('Invalid job id')
  }
  return normalized
}

export function listJobs(params = {}) {
  return toData(apiClient.get(`${API_BASE}/jobs`, { params }))
}

export function createJob(payload) {
  return toData(apiClient.post(`${API_BASE}/jobs`, payload))
}

export function startJob(jobId, payload = {}) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.post(`${API_BASE}/jobs/${id}/start`, payload))
}

export function getJob(jobId) {
  const id = normalizeJobId(jobId)
  return toData(apiClient.get(`${API_BASE}/jobs/${id}`))
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
