import apiClient from './client.js'
import { toData } from './data.js'

export function listJobs(params = {}) {
  return toData(apiClient.get('/api/jobs', { params }))
}

export function createJob(payload) {
  return toData(apiClient.post('/api/jobs', payload))
}

export function startJob(jobId) {
  return toData(apiClient.post(`/api/jobs/${jobId}/start`))
}

export function getJob(jobId) {
  return toData(apiClient.get(`/api/jobs/${jobId}`))
}

export function verifyJob(jobId) {
  return toData(apiClient.post(`/api/jobs/${jobId}/verify`))
}

export function generateManifest(jobId) {
  return toData(apiClient.post(`/api/jobs/${jobId}/manifest`))
}
