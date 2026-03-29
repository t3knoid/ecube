import AxeBuilder from '@axe-core/playwright'

export async function expectNoCriticalA11yViolations(page, options = {}) {
  const builder = new AxeBuilder({ page })
  if (options.context) {
    builder.include(options.context)
  }
  const results = await builder.analyze()
  const violations = (results.violations || []).filter((v) =>
    ['serious', 'critical'].includes(v.impact),
  )
  if (violations.length > 0) {
    const detail = violations
      .map((v) => {
        const targets = (v.nodes || []).flatMap((n) => n.target || []).join(', ')
        return `${v.id}${targets ? ` [${targets}]` : ''}`
      })
      .join(' | ')
    throw new Error(`Accessibility violations found: ${detail}`)
  }
}
