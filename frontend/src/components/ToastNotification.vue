<script setup>
import { useToast } from '@/composables/useToast.js'

const { toasts, removeToast } = useToast()

function typeClass(type) {
  return `toast--${type}`
}
</script>

<template>
  <Teleport to="body">
    <div class="toast-container" aria-live="polite" aria-atomic="false">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          :class="['toast', typeClass(toast.type)]"
          role="alert"
        >
          <span class="toast__message">{{ toast.message }}</span>
          <span v-if="toast.traceId" class="toast__trace">
            Ref: {{ toast.traceId }}
          </span>
          <button
            class="toast__close"
            aria-label="Close"
            @click="removeToast(toast.id)"
          >
            &times;
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-width: 28rem;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-radius: 0.375rem;
  color: #fff;
  font-size: 0.875rem;
  line-height: 1.4;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.toast--success {
  background-color: #16a34a;
}
.toast--info {
  background-color: #2563eb;
}
.toast--warning {
  background-color: #d97706;
}
.toast--error {
  background-color: #dc2626;
}

.toast__message {
  flex: 1;
}

.toast__trace {
  font-size: 0.75rem;
  opacity: 0.85;
  white-space: nowrap;
}

.toast__close {
  background: none;
  border: none;
  color: inherit;
  font-size: 1.25rem;
  line-height: 1;
  cursor: pointer;
  padding: 0;
  opacity: 0.8;
}

.toast__close:hover {
  opacity: 1;
}

/* Transition */
.toast-enter-active {
  transition: all 0.3s ease;
}
.toast-leave-active {
  transition: all 0.2s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(2rem);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(2rem);
}
</style>
