<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: {
    type: [String, Number, Boolean],
    default: null,
  },
  label: {
    type: String,
    default: '',
  },
})

const normalized = computed(() => String(props.status ?? 'unknown').toUpperCase())

const displayText = computed(() => props.label || String(props.status ?? 'unknown'))

const badgeClass = computed(() => {
  const value = normalized.value
  if (['COMPLETED', 'DONE', 'MOUNTED', 'CONNECTED', 'AVAILABLE', 'OK', 'TRUE'].includes(value)) {
    return 'badge-success'
  }
  if (['FAILED', 'ERROR', 'DISCONNECTED', 'UNMOUNTED', 'FALSE'].includes(value)) {
    return 'badge-danger'
  }
  if (['RUNNING', 'VERIFYING', 'COPYING', 'IN_USE', 'DEGRADED'].includes(value)) {
    return 'badge-warning'
  }
  if (['PENDING', 'EMPTY', 'UNKNOWN'].includes(value)) {
    return 'badge-muted'
  }
  return 'badge-info'
})
</script>

<template>
  <span class="status-badge" :class="badgeClass">
    {{ displayText }}
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 72px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  border: 1px solid transparent;
  text-transform: uppercase;
}

.badge-success {
  background: color-mix(in srgb, var(--color-success) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  color: var(--color-status-ok-text, #14532d);
}

.badge-warning {
  background: color-mix(in srgb, var(--color-warning) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-warning) 45%, var(--color-border));
  color: var(--color-status-warn-text, #7c3f00);
}

.badge-danger {
  background: color-mix(in srgb, var(--color-danger) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--color-border));
  color: var(--color-status-danger-text, #991b1b);
}

.badge-info {
  background: color-mix(in srgb, var(--color-info) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-info) 45%, var(--color-border));
  color: var(--color-status-info-text, #1e40af);
}

.badge-muted {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-status-muted-text, #475569);
}
</style>
