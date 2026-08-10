import { createRouter, createWebHistory } from 'vue-router'
import BotListView from '@/views/BotListView.vue'
import BotManageView from '@/views/BotManageView.vue'
import EventConfigView from '@/views/EventConfigView.vue'
import ApiConsoleView from '@/views/ApiConsoleView.vue'
import ChatView from '@/views/ChatView.vue'
import AiSettingsView from '@/views/AiSettingsView.vue'
import GroupVerificationView from '@/views/GroupVerificationView.vue'
import GroupManagementView from '@/views/GroupManagementView.vue'
import GroupModerationView from '@/views/GroupModerationView.vue'
import LibraryDeliveryView from '@/views/LibraryDeliveryView.vue'
import LoginView from '@/views/LoginView.vue'
import RegisterView from '@/views/RegisterView.vue'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true, authLayout: true } },
    { path: '/register', name: 'register', component: RegisterView, meta: { public: true, authLayout: true } },
    { path: '/', redirect: '/bots' },
    { path: '/bots', name: 'bots', component: BotListView },
    { path: '/bots/:id', name: 'bot-manage', component: BotManageView, props: true },
    { path: '/chat', name: 'chat', component: ChatView },
    { path: '/ai', name: 'ai', component: AiSettingsView },
    { path: '/events', name: 'events', component: EventConfigView },
    { path: '/group-management', name: 'group-management', component: GroupManagementView },
    { path: '/group-verification', redirect: to => ({ path: '/group-management', query: to.query }) },
    { path: '/group-verification-legacy', name: 'group-verification-legacy', component: GroupVerificationView },
    { path: '/group-moderation', name: 'group-moderation', component: GroupModerationView },
    { path: '/library-delivery', name: 'library-delivery', component: LibraryDeliveryView },
    { path: '/api-console', name: 'api-console', component: ApiConsoleView },
    { path: '/:pathMatch(.*)*', redirect: '/bots' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.bootstrapped) {
    await auth.bootstrap()
  }
  if (to.meta.public) {
    if (auth.isAuthenticated && (to.name === 'login' || to.name === 'register')) {
      return { path: '/bots' }
    }
    return true
  }
  if (!auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
