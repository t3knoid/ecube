<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { EXPIRED_QUERY_KEY, EXPIRED_QUERY_VALUE } from '@/constants/auth.js'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

const sessionExpired = computed(() => route.query[EXPIRED_QUERY_KEY] === EXPIRED_QUERY_VALUE)

async function handleLogin() {
  error.value = ''
  loading.value = true
  try {
    await authStore.login(username.value, password.value)
    router.push('/')
  } catch (err) {
    if (err.response?.data?.detail) {
      const detail = err.response.data.detail
      if (typeof detail === 'string') {
        error.value = detail
      } else if (Array.isArray(detail)) {
        // FastAPI 422 validation errors return detail as an array of objects
        error.value = detail.map((d) => d.msg || String(d)).join('; ')
      } else {
        error.value = t('common.errors.invalidRequest')
      }
    } else if (err.response) {
      // Server returned an unexpected error status
      error.value = t('common.errors.serverError', { status: err.response.status })
    } else if (err.name === 'TokenError') {
      error.value = err.message
    } else {
      // No response at all — network/CORS/proxy failure
      error.value = t('common.errors.networkError')
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <h1 class="login-title">{{ t('app.name') }}</h1>
        <p class="login-subtitle">{{ t('app.title') }}</p>
      </div>

      <div v-if="sessionExpired" class="session-expired-banner">
        <p><strong>{{ t('auth.sessionExpired') }}</strong></p>
        <p>{{ t('auth.sessionExpiredMessage') }}</p>
      </div>

      <form class="login-form" @submit.prevent="handleLogin">
        <div class="form-group">
          <label for="username">{{ t('auth.username') }}</label>
          <input
            id="username"
            v-model="username"
            type="text"
            autocomplete="username"
            required
            :disabled="loading"
          />
        </div>

        <div class="form-group">
          <label for="password">{{ t('auth.password') }}</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            :disabled="loading"
          />
        </div>

        <button type="submit" class="btn btn-primary" :disabled="loading">
          {{ loading ? t('auth.loggingIn') : t('auth.login') }}
        </button>
      </form>

      <div v-if="error" class="login-error" role="alert">
        {{ error }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--color-bg-primary);
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: var(--space-xl);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  box-shadow: var(--shadow-md);
}

.login-header {
  text-align: center;
  margin-bottom: var(--space-lg);
}

.login-title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
}

.login-subtitle {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin-top: var(--space-xs);
}

.session-expired-banner {
  background: var(--color-alert-warning-bg);
  color: var(--color-alert-warning-text);
  border: 1px solid var(--color-alert-warning-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm) var(--space-md);
  margin-bottom: var(--space-md);
  text-align: center;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.form-group label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
}

.form-group input {
  padding: var(--space-sm) var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  font-size: var(--font-size-base);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
}

.form-group input:focus {
  outline: 2px solid var(--color-border-focus);
  outline-offset: -1px;
}

.btn {
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--border-radius);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-bold);
  cursor: pointer;
}

.btn-primary {
  background: var(--color-btn-primary-bg);
  color: var(--color-btn-primary-text);
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-btn-primary-hover-bg);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.login-error {
  margin-top: var(--space-md);
  padding: var(--space-sm) var(--space-md);
  background: var(--color-alert-danger-bg);
  color: var(--color-alert-danger-text);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  text-align: center;
  font-size: var(--font-size-sm);
}
</style>
