const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

// VITE_API_BASE_URL — optional build-time override for cross-origin or
// two-machine deployments where the API is hosted on a different server.
//   Same-origin (default):  leave unset — API_BASE resolves to "/api".
//   Cross-origin example:   VITE_API_BASE_URL=https://api.corp.local:8443/api
const _explicit = import.meta.env.VITE_API_BASE_URL
export const API_BASE = _explicit
  ? _explicit.replace(/\/$/, '')
  : `${BASE}/api`

export const LOGIN_PATH = `${BASE}/login`
