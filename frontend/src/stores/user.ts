import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'
import type { UserInfo, LoginParams } from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const userInfo = ref<UserInfo | null>(null)
  const isLoggedIn = ref(!!token.value)

  async function login(params: LoginParams) {
    const res = await authApi.login(params)
    token.value = res.token
    userInfo.value = res.user
    isLoggedIn.value = true
    localStorage.setItem('token', res.token)
  }

  async function checkAuth() {
    try {
      const res = await authApi.getUserInfo()
      userInfo.value = res
      isLoggedIn.value = true
    } catch (error: any) {
      // 只有 401/403 才清除 token（认证失效），其他错误保留 token
      const status = error?.response?.status
      if (status === 401 || status === 403) {
        logout()
      }
      // 网络错误等不处理，保留 token 等下次重试
    }
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    isLoggedIn.value = false
    localStorage.removeItem('token')
  }

  return { token, userInfo, isLoggedIn, login, checkAuth, logout }
})
