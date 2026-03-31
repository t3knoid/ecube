// BASE strips the trailing slash from Vite's BASE_URL (e.g. "/" → "", "/app" → "/app").
// API_BASE therefore resolves to "{BASE_URL}/api" — "/api" for root builds,
// "/some-subpath/api" for sub-path builds.
// Set VITE_API_BASE_URL at build time to override for cross-origin deployments.
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')
export const API_BASE = `${BASE}/api`
export const LOGIN_PATH = `${BASE}/login`
