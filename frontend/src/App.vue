<script setup lang="ts">
import AppHeader from './components/AppHeader.vue'
import Home from './views/Home.vue'
import AppFooter from './components/AppFooter.vue'
</script>

<template>
  <div class="flex min-h-screen flex-col bg-canvas">
    <AppHeader />
    <main class="flex-1">
      <Home />
    </main>
    <AppFooter />
  </div>
</template>
