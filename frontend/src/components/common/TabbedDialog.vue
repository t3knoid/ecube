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
  gap: 0;
  min-height: 0;
}

.tabbed-dialog__tabs {
  background: color-mix(in srgb, var(--color-primary, #5aa9e6) 12%, var(--color-bg-primary) 88%);
  border: 1px solid var(--color-border);
  border-bottom: 0;
  border-radius: var(--border-radius-lg, calc(var(--border-radius) * 1.5)) var(--border-radius-lg, calc(var(--border-radius) * 1.5)) 0 0;
  display: flex;
  align-items: flex-end;
  overflow-x: auto;
  overflow-y: hidden;
  padding: var(--space-xs) var(--space-xs) 0;
  scrollbar-width: thin;
}

.tabbed-dialog__tab {
  appearance: none;
  border: 1px solid var(--color-border);
  border-bottom: 0;
  border-radius: var(--border-radius) var(--border-radius) 0 0;
  background: color-mix(in srgb, var(--color-bg-primary) 96%, white 4%);
  color: var(--color-text-secondary);
  cursor: pointer;
  font: inherit;
  font-weight: var(--font-weight-semibold);
  line-height: 1.2;
  margin-bottom: -1px;
  padding: var(--space-sm) var(--space-lg, var(--space-md));
  position: relative;
  transition:
    background-color 140ms ease,
    border-color 140ms ease,
    color 140ms ease,
    box-shadow 140ms ease;
  white-space: nowrap;
}

.tabbed-dialog__tab:hover {
  background: color-mix(in srgb, var(--color-primary, #5aa9e6) 6%, var(--color-bg-primary) 94%);
  color: var(--color-text-primary);
}

.tabbed-dialog__tab:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 1px var(--color-border-strong, var(--color-border));
}

.tabbed-dialog__tab--active {
  background: color-mix(in srgb, var(--color-primary, #5aa9e6) 5%, var(--color-bg-primary) 95%);
  border-color: var(--color-border);
  color: var(--color-text-primary);
  box-shadow: 0 -1px 0 color-mix(in srgb, var(--color-primary, var(--color-text-primary)) 28%, transparent);
  padding-bottom: calc(var(--space-sm) + 2px);
}

.tabbed-dialog__content {
  background: color-mix(in srgb, var(--color-primary, #5aa9e6) 5%, var(--color-bg-primary) 95%);
  border: 1px solid var(--color-border);
  border-radius: 0 0 var(--border-radius-lg, calc(var(--border-radius) * 1.5)) var(--border-radius-lg, calc(var(--border-radius) * 1.5));
  min-height: 0;
}

.tabbed-dialog__panel {
  min-height: 0;
  padding: var(--space-md);
}

@media (max-width: 768px) {
  .tabbed-dialog__tabs {
    gap: 0;
    padding-inline: var(--space-2xs, var(--space-xs));
  }

  .tabbed-dialog__tab {
    padding-inline: var(--space-sm);
  }
}
</style>
