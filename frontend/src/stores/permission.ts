import { defineStore } from 'pinia'
import { ref } from 'vue'
import { accessApi } from '@/api/admin'

/**
 * 当前账号的页面权限（来源：GET /auth/permissions/me）。
 *
 * 后端不可用时走降级：除 /admin/* 外全部放行，避免认证服务抖动把用户锁在登录页；
 * 后台管理页始终要求 isAdmin，降级期间不会误开。
 */
export const usePermissionStore = defineStore('permission', () => {
  const role = ref<string>('')
  const isAdmin = ref(false)
  const allowedPaths = ref<string[]>([])
  const loaded = ref(false)
  const degraded = ref(false)

  let pending: Promise<void> | null = null

  async function fetchMine(): Promise<void> {
    if (pending) return pending
    pending = (async () => {
      try {
        const res = await accessApi.getMyPermissions()
        role.value = res.role
        isAdmin.value = res.isAdmin
        allowedPaths.value = res.allowedPaths || []
        degraded.value = false
      } catch {
        role.value = 'USER'
        isAdmin.value = false
        allowedPaths.value = []
        degraded.value = true
      } finally {
        loaded.value = true
        pending = null
      }
    })()
    return pending
  }

  function can(path: string): boolean {
    if (degraded.value) return !path.startsWith('/admin')
    return allowedPaths.value.includes(path)
  }

  /** 无权访问时的落点：第一个被授权的页面 */
  function firstAllowed(): string {
    if (degraded.value) return '/'
    return allowedPaths.value[0] || '/'
  }

  /** 重新拉取（账号被改角色后由页面主动触发） */
  async function refresh(): Promise<void> {
    loaded.value = false
    await fetchMine()
  }

  function reset() {
    role.value = ''
    isAdmin.value = false
    allowedPaths.value = []
    loaded.value = false
    degraded.value = false
    pending = null
  }

  return { role, isAdmin, allowedPaths, loaded, degraded, fetchMine, can, firstAllowed, refresh, reset }
})
