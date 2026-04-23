import { STORAGE_TOKEN_KEY } from '../../src/constants/storage.js'

export function makeToken(payload) {
  const encode = (obj) =>
    Buffer.from(JSON.stringify(obj)).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
  return `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode(payload)}.fake_sig`
}

export async function routeJson(page, pattern, body, status = 200) {
  const matcher = typeof pattern === 'string' && !pattern.endsWith('**')
    ? `${pattern}**`
    : pattern

  await page.route(matcher, async (route) => {
    await route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(typeof body === 'function' ? body(route.request()) : body),
    })
  })
}

export async function stubSetupStatus(page, initialized = true) {
  await routeJson(page, '**/api/setup/status', { initialized })
  await routeJson(page, '**/setup/status', { initialized })
}

export async function stubSetupDatabaseBootstrap(page, {
  provisioned = false,
  systemInfo = {
    in_docker: false,
    suggested_db_host: 'localhost',
    suggested_admin_username: 'postgres',
  },
} = {}) {
  await routeJson(page, '**/api/setup/database/provision-status', { provisioned })
  await routeJson(page, '**/setup/database/provision-status', { provisioned })
  await routeJson(page, '**/api/setup/database/system-info', systemInfo)
  await routeJson(page, '**/setup/database/system-info', systemInfo)
}

export async function stubFooterApis(page) {
  await routeJson(page, '**/api/introspection/system-health', {
    status: 'ok',
    database: 'connected',
    active_jobs: 0,
  })
  await routeJson(page, '**/api/introspection/version', { version: 'test' })
  await routeJson(page, '**/api/auth/public-config', {
    auth_mode: 'local',
    oidc_enabled: false,
    oidc_login_label: null,
    local_login_enabled: true,
    session_backend: 'cookie',
  })
  await routeJson(page, '**/api/telemetry/ui-navigation', { ok: true })
  await routeJson(page, '**/telemetry/ui-navigation', { ok: true })
}

export async function stubTelemetryApis(page) {
  await routeJson(page, '**/api/telemetry/ui-navigation', { ok: true })
  await routeJson(page, '**/telemetry/ui-navigation', { ok: true })
}

export async function setupPublicPage(page, {
  initialized = true,
  provisioned = false,
  systemInfo,
} = {}) {
  await stubSetupStatus(page, initialized)
  await stubSetupDatabaseBootstrap(page, { provisioned, systemInfo })
  await stubFooterApis(page)
}

export async function stubDrivesApi(page, drives = []) {
  await routeJson(page, '**/api/drives**', drives)
}

export async function injectAuthToken(page, roles = ['admin']) {
  const exp = Math.floor(Date.now() / 1000) + 3600
  const jwt = makeToken({ sub: 'frank', roles, groups: [], exp })
  await page.addInitScript(({ token, key }) => {
    sessionStorage.setItem(key, token)
  }, { token: jwt, key: STORAGE_TOKEN_KEY })
}

export async function setupAuthenticatedPage(page, roles = ['admin']) {
  await setupPublicPage(page, { initialized: true })
  await injectAuthToken(page, roles)
}
