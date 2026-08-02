import { defineStore } from 'pinia'
import { authApi, type AuthUser } from '@/services/authApi'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as AuthUser | null,
    bootstrapped: false,
    loading: false,
    error: '',
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.user),
  },
  actions: {
    async bootstrap() {
      if (this.bootstrapped) return
      this.loading = true
      try {
        const result = await authApi.me()
        this.user = result.user
      } catch {
        this.user = null
      } finally {
        this.loading = false
        this.bootstrapped = true
      }
    },
    async login(email: string, password: string) {
      this.error = ''
      const result = await authApi.login(email, password)
      this.user = result.user
      this.bootstrapped = true
    },
    async register(email: string, password: string) {
      this.error = ''
      const result = await authApi.register(email, password)
      this.user = result.user
      this.bootstrapped = true
    },
    async logout() {
      try {
        await authApi.logout()
      } finally {
        this.user = null
      }
    },
    clearSession() {
      this.user = null
    },
  },
})
