<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import AppShell from '@/layouts/AppShell.vue'
import { setUnauthorizedHandler } from '@/services/http'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const useAuthLayout = computed(() => Boolean(route.meta.authLayout))

onMounted(() => {
  setUnauthorizedHandler(() => {
    auth.clearSession()
    if (route.name !== 'login' && route.name !== 'register') {
      router.replace({ path: '/login', query: { redirect: route.fullPath } })
    }
  })
})
</script>

<template>
  <RouterView v-if="useAuthLayout" />
  <AppShell v-else />
</template>
