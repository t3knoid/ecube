<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { useThemeStore } from '@/stores/theme.js'
import ThemeSwitcher from '@/components/ThemeSwitcher.vue'

const { t } = useI18n()
const authStore = useAuthStore()
const themeStore = useThemeStore()

const now = ref(Date.now())
const logoLoadFailed = ref(false)
const showHelpDialog = ref(false)
const helpDialogRef = ref(null)
const helpTriggerRef = ref(null)
let timerInterval = null

const showLogoImage = computed(() => Boolean(themeStore.currentLogo) && !logoLoadFailed.value)

watch(
  () => [themeStore.currentTheme, themeStore.currentLogo],
  () => {
    // Theme changes or logo URL changes should get a fresh load attempt.
    logoLoadFailed.value = false
  },
)

onMounted(() => {
  timerInterval = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
})

const remainingMinutes = computed(() => {
  if (!authStore.expiresAt) return null
  const diff = authStore.expiresAt - now.value
  if (diff <= 0) return 0
  return Math.ceil(diff / 60000)
})

const expiryWarning = computed(() => {
  return remainingMinutes.value !== null && remainingMinutes.value <= 5
})

function handleLogout() {
  authStore.logout()
}

function handleLogoError() {
  logoLoadFailed.value = true
}

function getFocusableElements(container) {
  if (!(container instanceof HTMLElement)) return []
  return Array.from(
    container.querySelectorAll(
      'button, [href], input, select, textarea, iframe, [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true')
}

function trapFocusWithin(event, container) {
  const focusable = getFocusableElements(container)
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement

  if (event.shiftKey && active === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

function openHelpDialog(event) {
  helpTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement
  showHelpDialog.value = true
}

function closeHelpDialog() {
  showHelpDialog.value = false
}

function handleHelpDialogKeydown(event) {
  if (!showHelpDialog.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeHelpDialog()
    return
  }
  if (event.key === 'Tab') {
    trapFocusWithin(event, helpDialogRef.value)
  }
}

watch(showHelpDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleHelpDialogKeydown)
    await nextTick()
    const firstFocusable = getFocusableElements(helpDialogRef.value)[0]
    if (firstFocusable instanceof HTMLElement) {
      firstFocusable.focus()
    }
    return
  }

  document.removeEventListener('keydown', handleHelpDialogKeydown)
  const trigger = helpTriggerRef.value
  helpTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleHelpDialogKeydown)
})
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <img
        v-if="showLogoImage"
        :src="themeStore.currentLogo"
        :alt="themeStore.currentLogoAlt"
        class="header-logo-image"
        @error="handleLogoError"
      />
      <span class="header-app-name">{{ t('app.name') }}</span>
    </div>
    <div class="header-right">
      <span class="header-username">{{ authStore.username }}</span>
      <span
        v-for="role in authStore.roles"
        :key="role"
        class="header-role-badge"
        :class="`badge-${role}`"
      >
        {{ role }}
      </span>
      <span
        v-if="remainingMinutes !== null"
        class="header-timer"
        :class="{ 'timer-warning': expiryWarning }"
        :aria-label="t('auth.sessionExpiresIn', remainingMinutes, { minutes: remainingMinutes })"
      >
        <span aria-hidden="true">⏱</span> {{ t('auth.sessionTimerShort', { minutes: remainingMinutes }) }}
      </span>
      <ThemeSwitcher />
      <button class="btn-help" @click="openHelpDialog">{{ t('help.open') }}</button>
      <button class="btn-logout" @click="handleLogout">{{ t('auth.logout') }}</button>
    </div>
  </header>
  <div v-if="showHelpDialog" class="help-overlay" @click.self="closeHelpDialog">
    <section
      ref="helpDialogRef"
      class="help-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="help-modal-title"
    >
      <div class="help-panel-header">
        <div>
          <p class="help-kicker">{{ t('help.kicker') }}</p>
          <h2 id="help-modal-title">{{ t('help.title') }}</h2>
        </div>
        <button class="btn-help-close" @click="closeHelpDialog">{{ t('common.actions.close') }}</button>
      </div>
      <p class="help-description">{{ t('help.description') }}</p>
      <iframe class="help-frame" :src="'/help/manual.html'" :title="t('help.frameTitle')" loading="lazy" />
    </section>
  </div>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-md);
  height: var(--header-height);
  background: var(--color-bg-header);
  border-bottom: 1px solid var(--color-border);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.header-logo-image {
  height: 88px;
  width: auto;
  max-width: 440px;
  object-fit: contain;
}

.header-app-name {
  font-weight: var(--font-weight-bold);
  font-size: var(--font-size-lg);
  color: var(--color-text-primary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.header-username {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.header-role-badge {
  display: inline-block;
  padding: var(--space-xs) var(--space-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  border-radius: 9999px;
  border: 1px solid var(--color-border);
  background: var(--color-badge-manager-bg);
  color: var(--color-badge-manager-text);
}

.badge-admin {
  background: var(--color-badge-admin-bg);
  color: var(--color-badge-admin-text);
}

.badge-manager {
  background: var(--color-badge-manager-bg);
  color: var(--color-badge-manager-text);
}

.badge-processor {
  background: var(--color-badge-processor-bg);
  color: var(--color-badge-processor-text);
}

.badge-auditor {
  background: var(--color-badge-auditor-bg);
  color: var(--color-badge-auditor-text);
}

.header-timer {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.timer-warning {
  color: var(--color-danger);
  font-weight: var(--font-weight-bold);
}

.btn-logout {
  padding: var(--space-xs) var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: transparent;
  color: var(--color-text-primary);
  cursor: pointer;
  font-size: var(--font-size-sm);
}

.btn-logout:hover {
  background: var(--color-bg-hover);
}

.btn-help,
.btn-help-close {
  padding: var(--space-xs) var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  cursor: pointer;
  font-size: var(--font-size-sm);
}

.btn-help:hover,
.btn-help-close:hover {
  background: var(--color-bg-hover);
}

.help-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-lg);
  background: rgba(15, 23, 42, 0.5);
  z-index: 1000;
}

.help-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  width: min(1040px, 100%);
  height: min(86vh, 820px);
  padding: var(--space-lg);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  box-shadow: var(--shadow-lg);
}

.help-panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
}

.help-kicker {
  margin: 0;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-text-secondary);
}

.help-panel-header h2,
.help-description {
  margin: 0;
}

.help-description {
  color: var(--color-text-secondary);
}

.help-frame {
  flex: 1;
  width: 100%;
  min-height: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: #fff;
}

@media (max-width: 840px) {
  .help-overlay {
    padding: var(--space-sm);
  }

  .help-panel {
    height: min(92vh, 920px);
    padding: var(--space-md);
  }

  .help-panel-header {
    flex-direction: column;
  }
}
</style>
