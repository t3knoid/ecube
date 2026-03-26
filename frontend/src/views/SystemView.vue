<script setup>
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>

<template>
  <div>
    <h1>{{ t('system.title') }}</h1>
    <p>{{ t('system.placeholder') }}</p>
  </div>
</template>
