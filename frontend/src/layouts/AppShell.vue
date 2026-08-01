<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import RobotMark from '@/components/RobotMark.vue'

const mobileOpen = ref(false)
const links = [
  { to: '/bots', label: '我的机器人', icon: 'bot' },
  { to: '/events', label: '事件与回调', icon: 'events' },
  { to: '/testers', label: '开发者测试', icon: 'users' },
  { to: '/api-console', label: 'API 调试台', icon: 'terminal' },
  { to: '/settings', label: '项目设置', icon: 'settings' },
]
</script>

<template>
  <div class="app-shell">
    <button class="mobile-menu" type="button" @click="mobileOpen = !mobileOpen" aria-label="打开菜单">☰</button>
    <aside class="sidebar" :class="{ open: mobileOpen }">
      <div class="brand">
        <RobotMark />
        <div>
          <div class="brand-name">QQ 机器人</div>
          <div class="brand-sub">开发与运营管理台</div>
        </div>
      </div>

      <nav class="nav">
        <RouterLink v-for="item in links" :key="item.to" :to="item.to" class="nav-item" @click="mobileOpen = false">
          <span class="nav-ico"><AppIcon :name="item.icon" /></span>
          <span>{{ item.label }}</span>
        </RouterLink>
        <a href="https://bot.q.qq.com/wiki/develop/api-v2/" target="_blank" rel="noopener noreferrer" class="nav-item">
          <span class="nav-ico"><AppIcon name="docs" /></span>
          <span>官方开发文档</span>
          <span class="external">↗</span>
        </a>
      </nav>

      <div class="sidebar-note">
        <div class="note-dot"></div>
        <div>
          <strong>开发模式</strong>
          <span>模拟数据已启用</span>
        </div>
      </div>

      <div class="account-card">
        <div class="account-avatar">DEV</div>
        <div class="account-text">
          <strong>本地开发者</strong>
          <span>密钥由后端管理</span>
        </div>
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
.nav-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 12px; border-radius: 14px; color: var(--ink-2); font-size: 13.5px; font-weight: 650; transition: .15s ease; }
.nav-item:hover { background: rgba(0,0,0,.04); }
.nav-item.router-link-active { background: var(--accent-soft); color: var(--accent); }
.nav-ico { width: 22px; height: 22px; display: grid; place-items: center; color: var(--ink-3); }
.router-link-active .nav-ico { color: var(--accent); }
.external { margin-left: auto; color: var(--ink-4); }
.sidebar-note { display: flex; align-items: center; gap: 10px; margin: 12px 0; padding: 11px 12px; border-radius: 14px; background: rgba(52,199,89,.08); color: #238541; }
.sidebar-note strong, .sidebar-note span { display: block; }
.sidebar-note strong { font-size: 12.5px; }
.sidebar-note span { margin-top: 2px; font-size: 10.5px; opacity: .75; }
.note-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--online); box-shadow: 0 0 0 4px rgba(52,199,89,.15); }
.account-card { display: flex; align-items: center; gap: 11px; padding: 13px; border: 1px solid rgba(60,60,67,.08); border-radius: 18px; box-shadow: 0 10px 24px rgba(17,24,39,.05); }
.account-avatar { width: 38px; height: 38px; display: grid; place-items: center; flex: none; border-radius: 50%; background: linear-gradient(135deg,#1b2735,#4b6584); color: white; font-size: 11px; font-weight: 800; }
.account-text { min-width: 0; }
.account-text strong, .account-text span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-text strong { font-size: 13px; }
.account-text span { margin-top: 3px; color: var(--ink-4); font-size: 10.5px; }
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
