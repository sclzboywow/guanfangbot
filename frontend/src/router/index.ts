import { createRouter, createWebHistory } from 'vue-router'
import BotListView from '@/views/BotListView.vue'
import BotManageView from '@/views/BotManageView.vue'
import EventConfigView from '@/views/EventConfigView.vue'
import ApiConsoleView from '@/views/ApiConsoleView.vue'
import GroupVerificationView from '@/views/GroupVerificationView.vue'
import GroupModerationView from '@/views/GroupModerationView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/bots' },
    { path: '/bots', name: 'bots', component: BotListView },
    { path: '/bots/:id', name: 'bot-manage', component: BotManageView, props: true },
    { path: '/events', name: 'events', component: EventConfigView },
    { path: '/group-verification', name: 'group-verification', component: GroupVerificationView },
    { path: '/group-moderation', name: 'group-moderation', component: GroupModerationView },
    { path: '/api-console', name: 'api-console', component: ApiConsoleView },
    { path: '/:pathMatch(.*)*', redirect: '/bots' },
  ],
})

export default router
