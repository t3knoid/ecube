<script setup>
import { computed, nextTick, onUnmounted, ref, useSlots, watch } from 'vue'

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

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])
const slots = useSlots()
const dialogPanelRef = ref(null)
const previousFocusRef = ref(null)

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
  emit('update:modelValue', false)
  emit('cancel')
}

function confirm() {
  emit('confirm')
}

function getFocusableElements() {
  if (!(dialogPanelRef.value instanceof HTMLElement)) {
    return []
  }

  return Array.from(
    dialogPanelRef.value.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  )
}

function focusFirstElement() {
  void nextTick(() => {
    const [firstElement] = getFocusableElements()
    firstElement?.focus()
  })
}

function restorePreviousFocus() {
  if (previousFocusRef.value instanceof HTMLElement) {
    previousFocusRef.value.focus()
  }
  previousFocusRef.value = null
}

function trapFocus(event) {
  const focusableElements = getFocusableElements()
  if (!focusableElements.length) {
    return
  }

  const firstElement = focusableElements[0]
  const lastElement = focusableElements[focusableElements.length - 1]
  const activeElement = document.activeElement

  if (event.shiftKey && activeElement === firstElement) {
    event.preventDefault()
    lastElement.focus()
    return
  }

  if (!event.shiftKey && activeElement === lastElement) {
    event.preventDefault()
    firstElement.focus()
  }
}

function onKeydown(event) {
  if (!props.modelValue) {
    return
  }

  if (event.key === 'Tab') {
    trapFocus(event)
    return
  }

  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

watch(
  () => props.modelValue,
  (open, wasOpen) => {
    if (open) {
      previousFocusRef.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
      document.addEventListener('keydown', onKeydown)
      focusFirstElement()
    } else {
      document.removeEventListener('keydown', onKeydown)
      if (wasOpen) {
        void nextTick(() => {
          restorePreviousFocus()
        })
      }
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <teleport to="body">
    <div v-if="modelValue" class="dialog-overlay" @click.self="close">
      <div
        ref="dialogPanelRef"
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
          <button class="btn" @click="close">{{ cancelLabel }}</button>
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
