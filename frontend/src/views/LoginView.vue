<script setup>
import { ref, computed, watch, onMounted } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { getPublicAuthConfig } from "@/api/auth.js";
import { useAuthStore } from "@/stores/auth.js";
import { useThemeStore } from "@/stores/theme.js";
import ConfirmDialog from "@/components/common/ConfirmDialog.vue";
import { EXPIRED_QUERY_KEY, EXPIRED_QUERY_VALUE } from "@/constants/auth.js";

const router = useRouter();
const route = useRoute();
const { t } = useI18n();
const authStore = useAuthStore();
const themeStore = useThemeStore();

const username = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);
const logoLoadFailed = ref(false);
const showPasswordChangeDialog = ref(false);
const passwordChangeBusy = ref(false);
const passwordChangeError = ref("");
const passwordChangeForm = ref({
  username: "",
  currentPassword: "",
  newPassword: "",
  confirmPassword: "",
});
const publicAuthConfig = ref({
  demo_mode_enabled: false,
  login_message: null,
  shared_password: null,
  demo_accounts: [],
  password_change_allowed: true,
});

const passwordPolicyHints = computed(() => [
  t("auth.passwordPolicy.minLength"),
  t("auth.passwordPolicy.characterClasses"),
  t("auth.passwordPolicy.maxRepeat"),
  t("auth.passwordPolicy.maxSequence"),
  t("auth.passwordPolicy.usernameCheck"),
  t("auth.passwordPolicy.dictionaryCheck"),
]);
const passwordChangeMismatch = computed(
  () =>
    !!passwordChangeForm.value.newPassword &&
    !!passwordChangeForm.value.confirmPassword &&
    passwordChangeForm.value.newPassword !== passwordChangeForm.value.confirmPassword,
);
const canSubmitPasswordChange = computed(
  () =>
    !!passwordChangeForm.value.username &&
    !!passwordChangeForm.value.currentPassword &&
    !!passwordChangeForm.value.newPassword &&
    !!passwordChangeForm.value.confirmPassword &&
    !passwordChangeMismatch.value,
);

const sessionExpired = computed(
  () => route.query[EXPIRED_QUERY_KEY] === EXPIRED_QUERY_VALUE,
);
const setupAlreadyInitialized = computed(
  () => route.query.reason === 'setup_already_initialized',
);
const showLogoImage = computed(
  () => Boolean(themeStore.currentLogo) && !logoLoadFailed.value,
);
const showDemoLoginPanel = computed(() => {
  const config = publicAuthConfig.value;
  return Boolean(
    config.demo_mode_enabled &&
    ((typeof config.login_message === "string" &&
      config.login_message.trim()) ||
      (typeof config.shared_password === "string" &&
        config.shared_password.trim()) ||
      config.demo_accounts.length),
  );
});

function isDemoPasswordLockedUser(usernameValue) {
  if (
    !publicAuthConfig.value.demo_mode_enabled ||
    publicAuthConfig.value.password_change_allowed !== false
  ) {
    return false;
  }

  return (publicAuthConfig.value.demo_accounts || []).some(
    (account) => account?.username === usernameValue,
  );
}

watch(
  () => themeStore.currentLogo,
  () => {
    logoLoadFailed.value = false;
  },
);

function handleLogoError() {
  logoLoadFailed.value = true;
}

onMounted(async () => {
  try {
    const config = await getPublicAuthConfig();
    const normalizedConfig = {
      demo_mode_enabled: Boolean(config?.demo_mode_enabled),
      login_message:
        typeof config?.login_message === "string" && config.login_message.trim()
          ? config.login_message.trim()
          : null,
      shared_password:
        typeof config?.shared_password === "string" &&
        config.shared_password.trim()
          ? config.shared_password.trim()
          : null,
      demo_accounts: Array.isArray(config?.demo_accounts)
        ? config.demo_accounts
            .map((account) => ({
              username:
                typeof account?.username === "string"
                  ? account.username.trim()
                  : "",
              label:
                typeof account?.label === "string" ? account.label.trim() : "",
              description:
                typeof account?.description === "string"
                  ? account.description.trim()
                  : "",
            }))
            .filter((account) => account.username)
        : [],
      password_change_allowed: config?.password_change_allowed !== false,
    };
    publicAuthConfig.value = normalizedConfig;
    if (normalizedConfig.shared_password && !password.value) {
      password.value = normalizedConfig.shared_password;
    }
  } catch {
    publicAuthConfig.value = {
      demo_mode_enabled: false,
      login_message: null,
      shared_password: null,
      demo_accounts: [],
      password_change_allowed: true,
    };
  }
});

async function handleLogin() {
  error.value = "";
  loading.value = true;
  const submittedUsername = username.value.trim();
  try {
    await authStore.login(submittedUsername, password.value);
    router.push("/");
  } catch (err) {
    const responseData = err.response?.data || {};
    if (responseData.reason === "password_expired") {
      if (isDemoPasswordLockedUser(submittedUsername)) {
        error.value = t("auth.demoPasswordManaged");
        return;
      }
      passwordChangeError.value = "";
      passwordChangeForm.value = {
        username: submittedUsername,
        currentPassword: password.value,
        newPassword: "",
        confirmPassword: "",
      };
      showPasswordChangeDialog.value = true;
      return;
    }
    if (
      typeof responseData.message === "string" &&
      responseData.message.trim()
    ) {
      error.value = responseData.message;
    } else if (responseData.detail) {
      const detail = responseData.detail;
      if (typeof detail === "string") {
        error.value = detail;
      } else if (Array.isArray(detail)) {
        // FastAPI 422 validation errors return detail as an array of objects
        error.value = detail.map((d) => d.msg || String(d)).join("; ");
      } else {
        error.value = t("common.errors.invalidRequest");
      }
    } else if (err.response) {
      // Server returned an unexpected error status
      error.value = t("common.errors.serverError", {
        status: err.response.status,
      });
    } else if (err.name === "TokenError") {
      error.value = err.message;
    } else {
      // No response at all — network/CORS/proxy failure
      error.value = t("common.errors.networkError");
    }
  } finally {
    loading.value = false;
  }
}

function closePasswordChangeDialog() {
  showPasswordChangeDialog.value = false;
  passwordChangeBusy.value = false;
  passwordChangeError.value = "";
  passwordChangeForm.value = {
    username: "",
    currentPassword: "",
    newPassword: "",
    confirmPassword: "",
  };
}

function handlePasswordChangeCancel() {
  password.value = "";
  closePasswordChangeDialog();
}

async function handlePasswordChangeConfirm() {
  if (!canSubmitPasswordChange.value) {
    return;
  }

  passwordChangeBusy.value = true;
  passwordChangeError.value = "";
  try {
    await authStore.changePassword(
      passwordChangeForm.value.username,
      passwordChangeForm.value.currentPassword,
      passwordChangeForm.value.newPassword,
    );
    closePasswordChangeDialog();
    router.push("/");
  } catch (err) {
    const responseData = err.response?.data || {};
    if (typeof responseData.message === "string" && responseData.message.trim()) {
      passwordChangeError.value = responseData.message;
    } else if (typeof responseData.detail === "string" && responseData.detail.trim()) {
      passwordChangeError.value = responseData.detail;
    } else {
      passwordChangeError.value = t("common.errors.validationFailed");
    }
  } finally {
    passwordChangeBusy.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <div class="login-title-row">
          <img
            v-if="showLogoImage"
            :src="themeStore.currentLogo"
            :alt="themeStore.currentLogoAlt"
            class="login-logo-image"
            @error="handleLogoError"
          />
          <h1 class="login-title">{{ t("app.name") }}</h1>
        </div>
        <p class="login-subtitle">{{ t("app.title") }}</p>
      </div>

      <div v-if="sessionExpired" class="session-expired-banner">
        <p>
          <strong>{{ t("auth.sessionExpired") }}</strong>
        </p>
        <p>{{ t("auth.sessionExpiredMessage") }}</p>
      </div>

      <div v-if="setupAlreadyInitialized" class="info-banner">
        <p>
          <strong>{{ t("setup.alreadyInitializedTitle") }}</strong>
        </p>
        <p>{{ t("setup.alreadyInitialized") }}</p>
      </div>

      <section
        v-if="showDemoLoginPanel"
        class="demo-login-panel"
        aria-labelledby="demo-login-heading"
      >
        <p id="demo-login-heading" class="demo-login-heading">
          <strong>{{ t("auth.demoAccess") }}</strong>
        </p>
        <p v-if="publicAuthConfig.login_message" class="demo-login-message">
          {{ publicAuthConfig.login_message }}
        </p>

        <p
          v-if="publicAuthConfig.shared_password"
          class="demo-login-message"
        >
          <strong>{{ t("auth.demoSharedPassword") }}:</strong>
          {{ publicAuthConfig.shared_password }}
        </p>

        <ul
          v-if="publicAuthConfig.demo_accounts.length"
          class="demo-account-list"
        >
          <li
            v-for="account in publicAuthConfig.demo_accounts"
            :key="account.username"
            class="demo-account-item"
          >
            <span class="demo-account-name">{{ account.username }}</span>
            <span v-if="account.label" class="demo-account-label">
              — {{ account.label }}</span
            >
            <p v-if="account.description" class="demo-account-description">
              {{ account.description }}
            </p>
          </li>
        </ul>

        <p
          v-if="!publicAuthConfig.password_change_allowed"
          class="demo-login-note"
        >
          {{ t("auth.demoPasswordManaged") }}
        </p>
      </section>

      <form class="login-form" @submit.prevent="handleLogin">
        <div class="form-group">
          <label for="username">{{ t("auth.username") }}</label>
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
          <label for="password">{{ t("auth.password") }}</label>
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
          {{ loading ? t("auth.loggingIn") : t("auth.login") }}
        </button>
      </form>

      <div v-if="error" class="login-error" role="alert">
        {{ error }}
      </div>
    </div>

    <ConfirmDialog
      v-model="showPasswordChangeDialog"
      :title="t('auth.passwordExpiredTitle')"
      :message="t('auth.passwordExpiredMessage')"
      :confirm-label="t('auth.changePassword')"
      :cancel-label="t('auth.logout')"
      :busy="passwordChangeBusy"
      :confirm-disabled="!canSubmitPasswordChange"
      :dismissible="false"
      @confirm="handlePasswordChangeConfirm"
      @cancel="handlePasswordChangeCancel"
    >
      <div class="password-change-grid">
        <div class="form-group">
          <label for="password-change-current">{{ t("auth.password") }}</label>
          <input
            id="password-change-current"
            v-model="passwordChangeForm.currentPassword"
            type="password"
            autocomplete="current-password"
          />
        </div>

        <div class="form-group">
          <label for="password-change-new">{{ t("auth.newPassword") }}</label>
          <input
            id="password-change-new"
            v-model="passwordChangeForm.newPassword"
            type="password"
            autocomplete="new-password"
            :aria-invalid="passwordChangeMismatch ? 'true' : 'false'"
            :aria-describedby="passwordChangeMismatch ? 'password-change-mismatch' : undefined"
          />
        </div>

        <div class="form-group">
          <label for="password-change-confirm">{{ t("auth.confirmPassword") }}</label>
          <input
            id="password-change-confirm"
            v-model="passwordChangeForm.confirmPassword"
            type="password"
            autocomplete="new-password"
            :aria-invalid="passwordChangeMismatch ? 'true' : 'false'"
            :aria-describedby="passwordChangeMismatch ? 'password-change-mismatch' : undefined"
          />
        </div>

        <p
          v-if="passwordChangeMismatch"
          id="password-change-mismatch"
          class="login-error"
          role="alert"
        >
          {{ t("auth.passwordMismatch") }}
        </p>

        <div class="policy-hints">
          <p class="policy-heading">{{ t("auth.passwordPolicy.title") }}</p>
          <ul class="policy-list">
            <li v-for="hint in passwordPolicyHints" :key="hint">{{ hint }}</li>
          </ul>
        </div>

        <p v-if="passwordChangeError" class="login-error" role="alert">
          {{ passwordChangeError }}
        </p>
      </div>
    </ConfirmDialog>
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

.login-title-row {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: var(--space-sm);
  max-width: 100%;
}

.login-logo-image {
  display: block;
  width: auto;
  max-width: 100%;
  height: 84px;
  object-fit: contain;
  flex-shrink: 1;
}

.login-title {
  margin: 0;
  min-width: 0;
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

.demo-login-panel {
  margin-bottom: var(--space-md);
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-tertiary);
}

.demo-login-heading {
  margin: 0 0 var(--space-xs);
  color: var(--color-text-primary);
}

.demo-login-message,
.demo-login-note {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.demo-login-note {
  margin-top: var(--space-xs);
}

.demo-account-list {
  margin: var(--space-sm) 0 0;
  padding-left: 1.1rem;
  display: grid;
  gap: var(--space-xs);
}

.demo-account-item {
  color: var(--color-text-primary);
}

.demo-account-name {
  font-weight: var(--font-weight-bold);
}

.demo-account-description {
  margin: 0.2rem 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
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

.password-change-grid {
  display: grid;
  gap: var(--space-sm);
}

.policy-hints {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-tertiary);
  padding: var(--space-sm);
}

.policy-heading {
  margin: 0 0 var(--space-xs);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
}

.policy-list {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--color-text-secondary);
}
</style>
