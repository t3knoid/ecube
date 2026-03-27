<script setup>
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>

<template>
  <div class="setup-wizard">
    <h1>{{ t('system.setup') }}</h1>
    <p>{{ t('system.setupPlaceholder') }}</p>
  </div>
</template>

<style scoped>
.setup-wizard {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: var(--space-md);
}
</style>
