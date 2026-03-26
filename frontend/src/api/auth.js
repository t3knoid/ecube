import apiClient from './client.js'

export function postLogin(username, password) {
  const params = new URLSearchParams()
  params.append('username', username)
  params.append('password', password)
  return apiClient.post('/auth/token', params, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
}
