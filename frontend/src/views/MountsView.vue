<script setup>
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>

<template>
  <div>
    <h1>{{ t('mounts.title') }}</h1>
    <p>{{ t('mounts.placeholder') }}</p>
  </div>
</template>
