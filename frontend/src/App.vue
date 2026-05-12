<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'

const userStore = useUserStore()
// Initialize theme store (triggers class application)
useThemeStore()

onMounted(() => {
  const token = localStorage.getItem('token')
  if (token) {
    userStore.checkAuth()
  }
})
</script>

<style lang="scss">
html, body, #app {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: var(--font-sans);
  background: var(--bg-primary);
  color: var(--text-primary);
}
</style>
