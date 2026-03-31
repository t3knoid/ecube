import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getSystemHealth() {
  return toData(apiClient.get(`${API_BASE}/introspection/system-health`))
}

export function getVersion() {
  return toData(apiClient.get(`${API_BASE}/introspection/version`))
}

export function getUsbTopology() {
  return toData(apiClient.get(`${API_BASE}/introspection/usb/topology`))
}

export function getBlockDevices() {
  return toData(apiClient.get(`${API_BASE}/introspection/block-devices`))
}

export function getSystemMounts() {
  return toData(apiClient.get(`${API_BASE}/introspection/mounts`))
}

export function getJobDebug(jobId) {
  return toData(apiClient.get(`${API_BASE}/introspection/jobs/${jobId}/debug`))
}
