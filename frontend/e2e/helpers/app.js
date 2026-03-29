import { STORAGE_TOKEN_KEY } from '../../src/constants/storage.js'

export function makeToken(payload) {
  const encode = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64')
  return `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode(payload)}.${encode('sig')}`
}

export async function routeJson(page, pattern, body, status = 200) {
  await page.route(pattern, async (route) => {
    await route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(typeof body === 'function' ? body(route.request()) : body),
    })
  })
}

export async function stubSetupStatus(page, initialized = true) {
  await routeJson(page, '**/api/setup/status', { initialized })
}

export async function stubFooterApis(page) {
  await routeJson(page, '**/api/introspection/system-health', {
    status: 'ok',
    database: 'connected',
    active_jobs: 0,
  })
  await routeJson(page, '**/api/introspection/version', { version: 'test' })
}

export async function injectAuthToken(page, roles = ['admin']) {
  const exp = Math.floor(Date.now() / 1000) + 3600
  const jwt = makeToken({ sub: 'frank', roles, groups: [], exp })
  await page.addInitScript(({ token, key }) => {
    sessionStorage.setItem(key, token)
  }, { token: jwt, key: STORAGE_TOKEN_KEY })
}

export async function setupAuthenticatedPage(page, roles = ['admin']) {
  await stubSetupStatus(page, true)
  await stubFooterApis(page)
  await injectAuthToken(page, roles)
}
