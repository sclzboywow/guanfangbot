import { defineStore } from 'pinia'
import { api, type Bot } from '@/services/api'

export const useBotsStore = defineStore('bots', {
  state: () => ({ bots: [] as Bot[], loading: false, error: '' }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try { this.bots = await api.listBots() }
      catch (error) { this.error = error instanceof Error ? error.message : '加载失败' }
      finally { this.loading = false }
    },
  },
})
