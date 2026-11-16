<script setup lang="ts">
import AppHeader from './components/AppHeader.vue'
import Home from './views/Home.vue'
import AppFooter from './components/AppFooter.vue'
import MembershipDialog from './components/MembershipDialog.vue'
import { provideMembership } from './membership'

provideMembership()
</script>

<template>
  <div class="studio-page flex min-h-screen flex-col">
    <AppHeader />
    <main class="flex-1">
      <Home />
    </main>
    <AppFooter />
    <MembershipDialog />
  </div>
</template>
