<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

const sessionExpired = computed(() => route.query.expired === '1')

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
        error.value = 'Invalid request. Please check your input.'
      }
    } else if (err.response) {
      // Server returned an unexpected error status
      error.value = `Server error (${err.response.status}). Please try again later.`
    } else if (err.name === 'TokenError') {
      error.value = err.message
    } else {
      // No response at all — network/CORS/proxy failure
      error.value = 'Unable to reach the server. Check your network connection and try again.'
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
        <h1 class="login-title">ECUBE</h1>
        <p class="login-subtitle">Evidence Copying &amp; USB Based Export</p>
      </div>

      <div v-if="sessionExpired" class="session-expired-banner">
        <p><strong>Session Expired</strong></p>
        <p>Your session has expired. Please log in again to continue.</p>
      </div>

      <form class="login-form" @submit.prevent="handleLogin">
        <div class="form-group">
          <label for="username">Username</label>
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
          <label for="password">Password</label>
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
          {{ loading ? 'Logging in…' : 'Log In' }}
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
  background: var(--color-background);
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 2rem;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-background-soft);
}

.login-header {
  text-align: center;
  margin-bottom: 1.5rem;
}

.login-title {
  font-size: 2rem;
  font-weight: 700;
  color: var(--color-heading);
}

.login-subtitle {
  font-size: 0.875rem;
  color: var(--color-text);
  margin-top: 0.25rem;
}

.session-expired-banner {
  background: #fff3cd;
  color: #856404;
  border: 1px solid #ffc107;
  border-radius: 4px;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  text-align: center;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--color-heading);
}

.form-group input {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  font-size: 1rem;
  background: var(--color-background);
  color: var(--color-text);
}

.form-group input:focus {
  outline: 2px solid #3b82f6;
  outline-offset: -1px;
}

.btn {
  padding: 0.625rem 1rem;
  border: none;
  border-radius: 4px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary {
  background: #3b82f6;
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.login-error {
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
  border-radius: 4px;
  text-align: center;
  font-size: 0.875rem;
}
</style>
