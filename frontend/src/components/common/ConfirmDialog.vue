<script setup>
import { computed, useSlots, watch, onUnmounted } from 'vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  title: {
    type: String,
    default: '',
  },
  message: {
    type: String,
    default: '',
  },
  confirmLabel: {
    type: String,
    required: true,
  },
  cancelLabel: {
    type: String,
    required: true,
  },
  dangerous: {
    type: Boolean,
    default: false,
  },
  busy: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'confirm'])
const slots = useSlots()

const dialogId = `confirm-dialog-${Math.random().toString(36).slice(2, 10)}`
const titleId = `${dialogId}-title`
const messageId = `${dialogId}-message`
const contentId = `${dialogId}-content`
const describedBy = computed(() => {
  const ids = []
  if (props.message) ids.push(messageId)
  if (slots.default) ids.push(contentId)
  return ids.length ? ids.join(' ') : undefined
})

function close() {
  if (props.busy) return
  emit('update:modelValue', false)
}

function confirm() {
  emit('confirm')
}

function onKeydown(event) {
  if (event.key === 'Escape' && props.modelValue) {
    event.preventDefault()
    close()
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      document.addEventListener('keydown', onKeydown)
    } else {
      document.removeEventListener('keydown', onKeydown)
    }
  },
)

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <teleport to="body">
    <div v-if="modelValue" class="dialog-overlay" @click.self="close">
      <div
        class="dialog-panel"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="describedBy"
      >
        <h3 :id="titleId" class="dialog-title">{{ title }}</h3>
        <p v-if="message" :id="messageId" class="dialog-message">{{ message }}</p>
        <div v-if="$slots.default" :id="contentId" class="dialog-content">
          <slot />
        </div>
        <div class="dialog-actions">
          <button class="btn" :disabled="busy" @click="close">{{ cancelLabel }}</button>
          <button
            class="btn"
            :class="dangerous ? 'btn-danger' : 'btn-primary'"
            :disabled="busy"
            @click="confirm"
          >
            {{ confirmLabel }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, var(--color-bg-primary) 30%, #000000);
  display: grid;
  place-items: center;
  z-index: 1000;
  padding: var(--space-md);
}

.dialog-panel {
  width: min(480px, 100%);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-lg);
}

.dialog-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin-bottom: var(--space-sm);
}

.dialog-message {
  color: var(--color-text-secondary);
  margin-bottom: var(--space-md);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}

.dialog-content {
  margin-bottom: var(--space-md);
}

</style>
