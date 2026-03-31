import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function postLogin(username, password) {
  return toData(apiClient.post(`${API_BASE}/auth/token`, { username, password }))
}
