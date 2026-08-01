import { createRouter, createWebHistory } from 'vue-router'
import BotListView from '@/views/BotListView.vue'
import BotManageView from '@/views/BotManageView.vue'
import EventConfigView from '@/views/EventConfigView.vue'
import TestersView from '@/views/TestersView.vue'
import ApiConsoleView from '@/views/ApiConsoleView.vue'
import SettingsView from '@/views/SettingsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/bots' },
    { path: '/bots', name: 'bots', component: BotListView },
    { path: '/bots/:id', name: 'bot-manage', component: BotManageView, props: true },
    { path: '/events', name: 'events', component: EventConfigView },
    { path: '/testers', name: 'testers', component: TestersView },
    { path: '/api-console', name: 'api-console', component: ApiConsoleView },
    { path: '/settings', name: 'settings', component: SettingsView },
  ],
})

export default router
