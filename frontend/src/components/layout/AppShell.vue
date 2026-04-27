<script setup>
import { onUnmounted, ref, watch } from 'vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppFooter from '@/components/layout/AppFooter.vue'

const sidebarOpen = ref(false)

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
}

function closeSidebar() {
  sidebarOpen.value = false
}

watch(sidebarOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})

onUnmounted(() => {
  document.body.style.overflow = ''
})
</script>

<template>
  <div class="app-shell">
    <AppHeader :sidebar-open="sidebarOpen" @toggle-sidebar="toggleSidebar" />
    <div class="shell-body">
      <div class="shell-backdrop" :class="{ 'shell-backdrop-open': sidebarOpen }" @click="closeSidebar" />
      <AppSidebar :sidebar-open="sidebarOpen" @close-sidebar="closeSidebar" />
      <main class="shell-content">
        <RouterView />
      </main>
    </div>
    <AppFooter />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--color-bg-primary);
}

.shell-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  position: relative;
}

.shell-content {
  flex: 1;
  padding: var(--space-lg);
  overflow-y: auto;
}

.shell-backdrop {
  display: none;
}

@media (max-width: 768px) {
  .shell-content {
    padding: var(--space-md);
  }

  .shell-backdrop {
    position: fixed;
    inset: var(--header-height) 0 0 0;
    display: block;
    background: rgba(15, 23, 42, 0.45);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease;
    z-index: 940;
  }

  .shell-backdrop-open {
    opacity: 1;
    pointer-events: auto;
  }
}
</style>
