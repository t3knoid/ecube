const PREFIX = '[ecube-ui]'

function _formatMessage(message) {
  return `${PREFIX} ${message}`
}

export const logger = {
  debug(message, context = undefined) {
    if (!import.meta.env.DEV) return
    if (context === undefined) {
      console.debug(_formatMessage(message))
      return
    }
    console.debug(_formatMessage(message), context)
  },

  info(message, context = undefined) {
    if (context === undefined) {
      console.info(_formatMessage(message))
      return
    }
    console.info(_formatMessage(message), context)
  },

  warn(message, context = undefined) {
    if (context === undefined) {
      console.warn(_formatMessage(message))
      return
    }
    console.warn(_formatMessage(message), context)
  },

  error(message, context = undefined) {
    if (context === undefined) {
      console.error(_formatMessage(message))
      return
    }
    console.error(_formatMessage(message), context)
  },
}
