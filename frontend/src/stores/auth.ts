import { defineStore } from 'pinia'
import { api, clearToken, getServer, getToken, setServer, setToken } from '../api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    server: getServer(),
    principal: null as any,
    deviceCount: 0,
    info: null as any,
  }),
  getters: {
    bound: (state) => Boolean(state.token),
  },
  actions: {
    async refresh() {
      if (!this.token) return
      try {
        const me = await api.get('/auth/me')
        this.principal = me.principal
        this.deviceCount = me.device_count
      } catch {
        /* 由 api 层处理 401 */
      }
    },
    async loadInfo() {
      this.info = await api.get('/info')
      return this.info
    },
    saveConnection(server: string, token: string) {
      setServer(server)
      setToken(token)
      this.server = server
      this.token = token
    },
    logout() {
      clearToken()
      this.token = ''
      this.principal = null
    },
  },
})
