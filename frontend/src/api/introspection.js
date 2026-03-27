import apiClient from './client.js'
import { toData } from './data.js'

export function getSystemHealth() {
  return toData(apiClient.get('/api/introspection/system-health'))
}

export function getVersion() {
  return toData(apiClient.get('/api/introspection/version'))
}

export function getUsbTopology() {
  return toData(apiClient.get('/api/introspection/usb/topology'))
}

export function getBlockDevices() {
  return toData(apiClient.get('/api/introspection/block-devices'))
}

export function getSystemMounts() {
  return toData(apiClient.get('/api/introspection/mounts'))
}

export function getJobDebug(jobId) {
  return toData(apiClient.get(`/api/introspection/jobs/${jobId}/debug`))
}
