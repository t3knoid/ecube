import { logger } from '@/utils/logger.js'
import { postUiNavigationTelemetry } from '@/api/telemetry.js'

function _trim(text, maxLength = 120) {
  const value = String(text || '').trim().replace(/\s+/g, ' ')
  if (!value) return ''
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength - 3)}...`
}

function _isExternalHref(href) {
  return /^(https?:|mailto:|tel:)/i.test(href)
}

function _extractElementLabel(element) {
  return (
    _trim(element.getAttribute('aria-label')) ||
    _trim(element.getAttribute('title')) ||
    _trim(element.textContent)
  )
}

function _extractDestination(element) {
  const navTarget = _trim(element.getAttribute('data-nav-target'))
  if (navTarget) return navTarget

  const href = _trim(element.getAttribute('href'))
  if (href) return href

  return 'same-page-action'
}

function _normalizeRoute(route) {
  return {
    name: route?.name ?? '(unnamed)',
    path: route?.path ?? '(unknown)',
    fullPath: route?.fullPath ?? route?.path ?? '(unknown)',
  }
}

function _resolveDestination(router, destination) {
  if (!router || !destination) return destination
  if (_isExternalHref(destination)) return destination
  if (destination === 'same-page-action') return destination

  try {
    const resolved = router.resolve(destination)
    if (resolved?.fullPath) {
      return resolved.fullPath
    }
  } catch {
    // Keep original destination when resolve fails.
  }
  return destination
}

function _isTrackableNavigation(destination, current) {
  if (!destination || destination === 'same-page-action') return false
  if (_isExternalHref(destination)) return false
  if (!destination.startsWith('/')) return false
  if (destination === current) return false
  return true
}

export function installNavigationTracing(router) {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return () => {}
  }

  const onClick = (event) => {
    const target = event.target instanceof Element ? event.target.closest('button, a, [role="button"]') : null
    if (!target) return

    const action = (target.tagName || 'element').toLowerCase()
    const label = _extractElementLabel(target)
    const rawDestination = _extractDestination(target)
    const destination = _resolveDestination(router, rawDestination)
    const current = window.location.pathname + window.location.search + window.location.hash

    if (!_isTrackableNavigation(destination, current)) {
      return
    }

    logger.debug('UI_NAVIGATION_CLICK', {
      action,
      label: label || '(no-label)',
      from: current,
      to: destination,
    })

    void postUiNavigationTelemetry({
      event_type: 'UI_NAVIGATION_CLICK',
      action,
      label: label || '(no-label)',
      source: current,
      destination,
    })
  }

  document.addEventListener('click', onClick, true)

  const stopAfterEach = router?.afterEach?.((to, from, failure) => {
    const toRoute = _normalizeRoute(to)
    const fromRoute = _normalizeRoute(from)

    if (failure) {
      logger.debug('UI_NAVIGATION_AFTER_EACH_FAILURE', {
        from: fromRoute.fullPath,
        to: toRoute.fullPath,
        reason: String(failure),
      })
      return
    }

    logger.debug('UI_NAVIGATION_COMPLETED', {
      from: fromRoute.fullPath,
      to: toRoute.fullPath,
      route_name: toRoute.name,
    })

    void postUiNavigationTelemetry({
      event_type: 'UI_NAVIGATION_COMPLETED',
      source: fromRoute.fullPath,
      destination: toRoute.fullPath,
      route_name: toRoute.name,
    })
  })

  return () => {
    document.removeEventListener('click', onClick, true)
    if (typeof stopAfterEach === 'function') {
      stopAfterEach()
    }
  }
}
