<script setup>
import AppHeader from '@/components/layout/AppHeader.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppFooter from '@/components/layout/AppFooter.vue'
</script>

<template>
  <div class="app-shell">
    <AppHeader />
    <div class="shell-body">
      <AppSidebar />
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
}

.shell-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.shell-content {
  flex: 1;
  padding: 1.5rem;
  overflow-y: auto;
}
</style>
