import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function listJobs(params = {}) {
  return toData(apiClient.get(`${API_BASE}/jobs`, { params }))
}

export function createJob(payload) {
  return toData(apiClient.post(`${API_BASE}/jobs`, payload))
}

export function startJob(jobId) {
  return toData(apiClient.post(`${API_BASE}/jobs/${jobId}/start`))
}

export function getJob(jobId) {
  return toData(apiClient.get(`${API_BASE}/jobs/${jobId}`))
}

export function getJobFiles(jobId) {
  return toData(apiClient.get(`${API_BASE}/jobs/${jobId}/files`))
}

export function verifyJob(jobId) {
  return toData(apiClient.post(`${API_BASE}/jobs/${jobId}/verify`))
}

export function generateManifest(jobId) {
  return toData(apiClient.post(`${API_BASE}/jobs/${jobId}/manifest`))
}
