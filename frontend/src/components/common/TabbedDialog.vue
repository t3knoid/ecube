<script setup>
import { ref } from 'vue'

const props = defineProps({
  tabs: {
    type: Array,
    required: true,
  },
  activeTab: {
    type: String,
    required: true,
  },
  ariaLabel: {
    type: String,
    default: '',
  },
  idPrefix: {
    type: String,
    default: 'tabbed-dialog',
  },
})

const emit = defineEmits(['update:activeTab'])

const tabButtonRefs = ref({})

function setTabButtonRef(key, element) {
  if (element) {
    tabButtonRefs.value[key] = element
    return
  }

  delete tabButtonRefs.value[key]
}

function focusTabButton(key) {
  tabButtonRefs.value[key]?.focus?.()
}

function activateTab(key, { focus = false } = {}) {
  if (!props.tabs.some((tab) => tab.key === key)) {
    return
  }

  emit('update:activeTab', key)

  if (focus) {
    focusTabButton(key)
  }
}

function handleTabKeydown(event, index) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
    return
  }

  event.preventDefault()

  if (event.key === 'Home') {
    activateTab(props.tabs[0].key, { focus: true })
    return
  }

  if (event.key === 'End') {
    activateTab(props.tabs[props.tabs.length - 1].key, { focus: true })
    return
  }

  const offset = event.key === 'ArrowRight' ? 1 : -1
  const nextIndex = (index + offset + props.tabs.length) % props.tabs.length
  activateTab(props.tabs[nextIndex].key, { focus: true })
}

function tabId(key) {
  return `${props.idPrefix}-tab-${key}`
}

function panelId(key) {
  return `${props.idPrefix}-panel-${key}`
}
</script>

<template>
  <div class="tabbed-dialog">
    <div class="tabbed-dialog__tabs" role="tablist" :aria-label="ariaLabel">
      <button
        v-for="(tab, index) in tabs"
        :id="tabId(tab.key)"
        :key="tab.key"
        :ref="(element) => setTabButtonRef(tab.key, element)"
        type="button"
        class="tabbed-dialog__tab"
        :class="{ 'tabbed-dialog__tab--active': activeTab === tab.key }"
        role="tab"
        :aria-selected="activeTab === tab.key"
        :aria-controls="panelId(tab.key)"
        :tabindex="activeTab === tab.key ? 0 : -1"
        @click="activateTab(tab.key)"
        @keydown="handleTabKeydown($event, index)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="tabbed-dialog__content">
      <div
        v-for="tab in tabs"
        v-show="activeTab === tab.key"
        :id="panelId(tab.key)"
        :key="tab.key"
        class="tabbed-dialog__panel"
        role="tabpanel"
        :aria-labelledby="tabId(tab.key)"
      >
        <slot :name="`panel-${tab.key}`" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.tabbed-dialog {
  display: grid;
  gap: var(--space-md);
  min-height: 0;
}

.tabbed-dialog__tabs {
  display: flex;
  gap: var(--space-xs);
  align-items: flex-end;
  border-bottom: 1px solid var(--color-border);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

.tabbed-dialog__tab {
  appearance: none;
  border: 0;
  border-radius: var(--border-radius) var(--border-radius) 0 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  font: inherit;
  font-weight: var(--font-weight-semibold);
  margin-bottom: -1px;
  padding: var(--space-sm) var(--space-md);
  white-space: nowrap;
}

.tabbed-dialog__tab:hover,
.tabbed-dialog__tab:focus-visible {
  color: var(--color-text-primary);
  outline: none;
}

.tabbed-dialog__tab:focus-visible {
  box-shadow: inset 0 0 0 1px var(--color-border-strong, var(--color-border));
}

.tabbed-dialog__tab--active {
  color: var(--color-text-primary);
  border-bottom-color: var(--color-primary, var(--color-text-primary));
}

.tabbed-dialog__content,
.tabbed-dialog__panel {
  min-height: 0;
}

@media (max-width: 768px) {
  .tabbed-dialog__tabs {
    gap: 0;
  }

  .tabbed-dialog__tab {
    padding-inline: var(--space-sm);
  }
}
</style>
