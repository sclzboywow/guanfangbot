<script setup lang="ts">
defineProps<{ name: string; size?: number }>()
</script>

<template>
  <span class="icon" :style="{ width: `${size || 18}px`, height: `${size || 18}px` }" aria-hidden="true">
    <svg v-if="name === 'bot'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="7" width="16" height="12" rx="4"/><path d="M12 3v4M8.5 12h.01M15.5 12h.01M8 16h8"/></svg>
    <svg v-else-if="name === 'events'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 6h16M4 12h10M4 18h7"/><circle cx="18" cy="15" r="3"/><path d="M18 11v1M18 18v1M14 15h1M21 15h1"/></svg>
    <svg v-else-if="name === 'users'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>
    <svg v-else-if="name === 'terminal'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/></svg>
    <svg v-else-if="name === 'shield'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 5 6v5c0 4.6 2.9 8 7 10 4.1-2 7-5.4 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-5"/></svg>
    <svg v-else-if="name === 'library'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 0 4 22.5v-17Z"/><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M8 7h8M8 11h6"/></svg>
    <svg v-else-if="name === 'sparkles'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m12 3 1.2 3.4L16.5 8l-3.3 1.6L12 13l-1.2-3.4L7.5 8l3.3-1.6L12 3Z"/><path d="m18.5 13 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2ZM5 12l.9 2.6L8.5 16l-2.6 1.4L5 20l-.9-2.6L1.5 16l2.6-1.4L5 12Z"/></svg>
    <svg v-else-if="name === 'settings'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H9.6v-.1A1.7 1.7 0 0 0 8 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 3.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H2V9.6h.1A1.7 1.7 0 0 0 3.6 8a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 8 3.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V2h4v.1A1.7 1.7 0 0 0 15 3.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 8c.37.3.58.76.6 1.2V9.6h2v4h-.1A1.7 1.7 0 0 0 19.4 15Z"/></svg>
    <svg v-else-if="name === 'docs'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg>
    <svg v-else-if="name === 'plus'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
    <svg v-else-if="name === 'arrow'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg>
    <svg v-else-if="name === 'copy'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/></svg>
  </span>
</template>

<style scoped>
.icon { display: inline-flex; flex: none; line-height: 0; }
.icon svg { width: 100%; height: 100%; display: block; }
</style>
