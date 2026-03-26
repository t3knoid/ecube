<script setup>
import { useThemeStore } from '@/stores/theme.js'
import { useI18n } from 'vue-i18n'

const themeStore = useThemeStore()
const { t } = useI18n()

function onThemeChange(event) {
  themeStore.loadTheme(event.target.value)
}
</script>

<template>
  <label class="theme-switcher" :title="t('common.labels.theme')">
    <span class="sr-only">{{ t('common.labels.theme') }}</span>
    <select
      :value="themeStore.currentTheme"
      class="theme-select"
      @change="onThemeChange"
    >
      <option
        v-for="theme in themeStore.availableThemes"
        :key="theme.name"
        :value="theme.name"
      >
        {{ theme.label }}
      </option>
    </select>
  </label>
</template>

<style scoped>
.theme-switcher {
  display: inline-flex;
  align-items: center;
}

.theme-select {
  padding: 0.25rem 0.5rem;
  font-size: var(--font-size-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  cursor: pointer;
}

.theme-select:focus {
  outline: 2px solid var(--color-border-focus);
  outline-offset: -1px;
}
</style>
