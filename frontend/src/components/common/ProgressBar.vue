<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

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
    default: '',
  },
  fullWidth: {
    type: Boolean,
    default: false,
  },
  active: {
    type: Boolean,
    default: false,
  },
})

const percentage = computed(() => {
  if (typeof props.value !== 'number' || typeof props.total !== 'number' || props.total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((props.value / props.total) * 100)))
})

const isIndeterminate = computed(() => props.active && percentage.value === 0)
const renderedWidth = computed(() => (isIndeterminate.value ? '35%' : `${percentage.value}%`))
const resolvedLabel = computed(() => props.label || `${percentage.value}%`)
const resolvedAriaLabel = computed(() => props.ariaLabel || t('common.labels.progress'))
</script>

<template>
  <div class="progress-wrap" :class="{ 'progress-wrap--full': fullWidth }">
    <div
      class="progress-track"
      :class="{ 'progress-track--full': fullWidth }"
      role="progressbar"
      :aria-label="resolvedAriaLabel"
      :aria-valuemin="0"
      :aria-valuemax="100"
      :aria-valuenow="percentage"
    >
      <div
        class="progress-bar"
        :class="{ 'progress-bar--active': active, 'progress-bar--indeterminate': isIndeterminate }"
        :style="{ width: renderedWidth }"
      />
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

.progress-wrap--full {
  width: 100%;
}

.progress-track {
  width: 140px;
  height: 8px;
  border-radius: 999px;
  background: var(--color-progress-track);
  overflow: hidden;
}

.progress-track--full {
  width: 100%;
  flex: 1 1 auto;
}

.progress-bar {
  height: 100%;
  background: var(--color-progress-bar);
  transition: width 0.25s ease;
}

.progress-bar--active {
  background-image: linear-gradient(
    90deg,
    var(--color-progress-bar) 0%,
    color-mix(in srgb, var(--color-progress-bar) 72%, white) 50%,
    var(--color-progress-bar) 100%
  );
  background-size: 200% 100%;
  animation: progress-slide 1.4s linear infinite;
}

.progress-bar--indeterminate {
  min-width: 2.5rem;
}

.progress-label {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  white-space: nowrap;
}

@keyframes progress-slide {
  from {
    background-position: 200% 0;
  }

  to {
    background-position: -200% 0;
  }
}
</style>