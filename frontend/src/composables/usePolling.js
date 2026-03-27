import { onBeforeUnmount, ref } from 'vue'

export function usePolling(fetchFn, options = {}) {
  const {
    intervalMs = 3000,
    isTerminal = () => false,
    immediate = true,
    allowOverlap = false,
  } = options

  const isPolling = ref(false)
  const lastResponse = ref(null)
  const lastError = ref(null)

  let timer = null
  let inFlight = false
  let seq = 0
  let runId = 0

  function scheduleNextTick() {
    if (!isPolling.value || allowOverlap) return

    timer = setTimeout(() => {
      tick()
        .catch(() => {})
        .finally(() => {
          scheduleNextTick()
        })
    }, intervalMs)
  }

  async function tick() {
    if (!allowOverlap && inFlight) return

    const currentSeq = ++seq
    const currentRunId = runId
    inFlight = true

    try {
      const response = await fetchFn()

      // Ignore results from a stopped/restarted polling run.
      if (currentRunId !== runId || !isPolling.value) return response

      // Discard stale responses when overlap is allowed.
      if (allowOverlap && currentSeq !== seq) return

      lastResponse.value = response
      lastError.value = null

      if (isTerminal(response)) {
        stop()
      }

      return response
    } catch (error) {
      if ((!allowOverlap || currentSeq === seq) && currentRunId === runId && isPolling.value) {
        lastError.value = error
      }
      throw error
    } finally {
      if (!allowOverlap || currentSeq === seq) {
        inFlight = false
      }
    }
  }

  function start() {
    if (isPolling.value) return

    runId += 1
    isPolling.value = true

    if (allowOverlap) {
      if (immediate) {
        // Fire and forget initial fetch; callers can use lastError for failures.
        tick().catch(() => {})
      }

      timer = setInterval(() => {
        tick().catch(() => {})
      }, intervalMs)
      return
    }

    if (immediate) {
      tick()
        .catch(() => {})
        .finally(() => {
          scheduleNextTick()
        })
      return
    }

    scheduleNextTick()
  }

  function stop() {
    runId += 1
    isPolling.value = false
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  onBeforeUnmount(stop)

  return {
    start,
    stop,
    tick,
    isPolling,
    lastResponse,
    lastError,
  }
}
