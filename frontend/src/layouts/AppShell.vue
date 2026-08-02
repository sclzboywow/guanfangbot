<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import RobotMark from '@/components/RobotMark.vue'
import { useAuthStore } from '@/stores/auth'

const mobileOpen = ref(false)
const router = useRouter()
const auth = useAuthStore()
const coreLinks = [
  { to: '/bots', label: '我的机器人', icon: 'bot' },
  { to: '/chat', label: '好友聊天', icon: 'users' },
  { to: '/events', label: '事件调试', icon: 'events' },
  { to: '/api-console', label: 'OpenAPI 调试', icon: 'terminal' },
]
const featureLinks = [
  { to: '/group-verification', label: '入群验证', icon: 'shield' },
  { to: '/group-moderation', label: '群消息治理', icon: 'shield' },
  { to: '/library-delivery', label: '共享文库', icon: 'library' },
]

async function logout() {
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <div class="app-shell">
    <button class="mobile-menu" type="button" @click="mobileOpen = !mobileOpen" aria-label="打开菜单">☰</button>
    <aside class="sidebar" :class="{ open: mobileOpen }">
      <div class="brand">
        <RobotMark />
        <div>
          <div class="brand-name">QQ 机器人</div>
          <div class="brand-sub">官方机器人开发台</div>
        </div>
      </div>

      <nav class="nav">
        <RouterLink v-for="item in coreLinks" :key="item.to" :to="item.to" class="nav-item" @click="mobileOpen = false">
          <span class="nav-ico"><AppIcon :name="item.icon" /></span>
          <span>{{ item.label }}</span>
        </RouterLink>

        <div class="nav-section">功能开发</div>
        <RouterLink v-for="item in featureLinks" :key="item.to" :to="item.to" class="nav-item" @click="mobileOpen = false">
          <span class="nav-ico"><AppIcon :name="item.icon" /></span>
          <span>{{ item.label }}</span>
        </RouterLink>

        <div class="nav-section">文档</div>
        <a href="https://bot.q.qq.com/wiki/develop/api-v2/" target="_blank" rel="noopener noreferrer" class="nav-item">
          <span class="nav-ico"><AppIcon name="docs" /></span>
          <span>官方开发文档</span>
          <span class="external">↗</span>
        </a>
      </nav>

      <div class="sidebar-summary">
        <strong>{{ auth.user?.email || '未登录' }}</strong>
        <span>{{ auth.user?.role === 'admin' ? '管理员工作区' : '独立租户工作区' }}</span>
        <button class="btn ghost logout" type="button" @click="logout">退出登录</button>
      </div>
    </aside>
    <div v-if="mobileOpen" class="mask" @click="mobileOpen = false"></div>
    <main class="main"><RouterView /></main>
  </div>
</template>

<style scoped>
.app-shell { display: grid; grid-template-columns: 260px minmax(0, 1fr); min-height: 100vh; }
.sidebar { position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; padding: 22px 16px 16px; background: white; border-right: 1px solid var(--line); z-index: 30; }
.brand { display: flex; align-items: center; gap: 10px; padding: 4px 8px 20px; margin-bottom: 18px; border-bottom: 1px solid var(--line); }
.brand-name { font-size: 15px; font-weight: 750; }
.brand-sub { margin-top: 2px; color: var(--ink-4); font-size: 11px; }
.nav { flex: 1; display: flex; flex-direction: column; gap: 6px; overflow-y: auto; }
.nav-section { margin: 14px 10px 3px; color: var(--ink-4); font-size: 9.5px; font-weight: 750; letter-spacing: .08em; }
.nav-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 12px; border-radius: 14px; color: var(--ink-2); font-size: 13.5px; font-weight: 650; transition: .15s ease; }
.nav-item:hover { background: rgba(0,0,0,.04); }
.nav-item.router-link-active { background: var(--accent-soft); color: var(--accent); }
.nav-ico { width: 22px; height: 22px; display: grid; place-items: center; color: var(--ink-3); }
.router-link-active .nav-ico { color: var(--accent); }
.external { margin-left: auto; color: var(--ink-4); }
.sidebar-summary { padding: 14px; border: 1px solid rgba(60,60,67,.08); border-radius: 18px; background: #fff; box-shadow: 0 10px 24px rgba(17,24,39,.05); }
.sidebar-summary strong, .sidebar-summary span { display: block; }
.sidebar-summary strong { color: var(--ink); font-size: 12.5px; word-break: break-all; }
.sidebar-summary span { margin-top: 5px; color: var(--ink-4); font-size: 10.5px; line-height: 1.5; }
.logout { margin-top: 10px; width: 100%; min-height: 34px; justify-content: center; }
.main { min-width: 0; min-height: 100vh; }
.mobile-menu { display: none; }
.mask { display: none; }
@media (max-width: 860px) {
  .app-shell { grid-template-columns: 1fr; }
  .sidebar { position: fixed; left: 0; transform: translateX(-105%); width: 260px; transition: transform .2s ease; box-shadow: var(--shadow-lg); }
  .sidebar.open { transform: translateX(0); }
  .mobile-menu { display: grid; place-items: center; position: fixed; right: 16px; top: 14px; z-index: 25; width: 42px; height: 42px; border: 1px solid var(--line); border-radius: 13px; background: rgba(255,255,255,.94); box-shadow: var(--shadow-sm); }
  .mask { display: block; position: fixed; inset: 0; z-index: 20; background: rgba(0,0,0,.25); backdrop-filter: blur(2px); }
}
</style>
