<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: {
    type: Number,
    default: 0,
  },
  total: {
    type: Number,
    default: 100,
  },
  showLabel: {
    type: Boolean,
    default: true,
  },
  label: {
    type: String,
    default: '',
  },
  ariaLabel: {
    type: String,
    default: 'Progress',
  },
})

const percentage = computed(() => {
  if (typeof props.value !== 'number' || typeof props.total !== 'number' || props.total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((props.value / props.total) * 100)))
})

const resolvedLabel = computed(() => props.label || `${percentage.value}%`)
</script>

<template>
  <div class="progress-wrap">
    <div
      class="progress-track"
      role="progressbar"
      :aria-label="ariaLabel"
      :aria-valuemin="0"
      :aria-valuemax="100"
      :aria-valuenow="percentage"
    >
      <div class="progress-bar" :style="{ width: `${percentage}%` }" />
    </div>
    <span v-if="showLabel" class="progress-label">{{ resolvedLabel }}</span>
  </div>
</template>

<style scoped>
.progress-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.progress-track {
  width: 140px;
  height: 8px;
  border-radius: 999px;
  background: var(--color-progress-track);
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: var(--color-progress-bar);
}

.progress-label {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>