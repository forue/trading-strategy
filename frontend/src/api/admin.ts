import request from './request'

export type RoleKey = 'USER' | 'ADMIN'

/** 后台账号管理用到的账号视图（不含密码） */
export interface AdminUser {
  id: number
  username: string
  email: string | null
  phone: string | null
  role: RoleKey
  status: 'ACTIVE' | 'DISABLED'
  createdAt: string
}

export interface UserPage {
  items: AdminUser[]
  total: number
  page: number
  size: number
}

export interface UserFormPayload {
  username?: string
  password?: string
  email?: string
  phone?: string
  role?: RoleKey
  status?: string
}

/** 页面权限：routes 是后端维护的页面清单，permissions 是角色 → 可访问路径 */
export interface RouteDef {
  path: string
  name: string
  group: string
  adminOnly: boolean
}

export interface RoutePermissionData {
  routes: RouteDef[]
  permissions: Record<string, string[]>
  lockedPaths: string[]
}

export interface FeatureQuotaRole {
  role: RoleKey
  dailyLimit: number
  enabled: boolean
}

export interface FeatureQuota {
  key: string
  name: string
  description: string
  roles: FeatureQuotaRole[]
}

export interface QuotaItemPayload {
  featureKey: string
  role: RoleKey
  dailyLimit: number
  enabled: boolean
}

/** 当前登录用户自己的权限与配额 */
export interface MyPermission {
  id: number
  username: string
  role: RoleKey
  isAdmin: boolean
  allowedPaths: string[]
}

export interface QuotaState {
  featureKey: string
  featureName: string
  enabled: boolean
  /** 0 = 不限次 */
  dailyLimit: number
  used: number
  /** -1 = 不限次 */
  remaining: number
}

export const adminApi = {
  listUsers(params: { keyword?: string; role?: string; page?: number; size?: number }): Promise<UserPage> {
    return request.get('/auth/admin/users', { params })
  },

  createUser(payload: UserFormPayload): Promise<AdminUser> {
    return request.post('/auth/admin/users', payload)
  },

  updateUser(id: number, payload: UserFormPayload): Promise<AdminUser> {
    return request.put(`/auth/admin/users/${id}`, payload)
  },

  deleteUser(id: number): Promise<void> {
    return request.delete(`/auth/admin/users/${id}`)
  },

  getRoutePermissions(): Promise<RoutePermissionData> {
    return request.get('/auth/admin/route-permissions')
  },

  saveRoutePermissions(role: RoleKey, allowedPaths: string[]): Promise<RoutePermissionData> {
    return request.put('/auth/admin/route-permissions', { role, allowedPaths })
  },

  getFeatureQuotas(): Promise<FeatureQuota[]> {
    return request.get('/auth/admin/feature-quotas')
  },

  saveFeatureQuotas(items: QuotaItemPayload[]): Promise<FeatureQuota[]> {
    return request.put('/auth/admin/feature-quotas', { items })
  },
}

/** 面向所有登录用户（不限于管理员） */
export const accessApi = {
  getMyPermissions(): Promise<MyPermission> {
    return request.get('/auth/permissions/me')
  },

  /** X-Silent：配额读数失败不弹全局错误，页面按「不显示」处理 */
  getMyQuota(feature: string): Promise<QuotaState> {
    return request.get('/auth/quota/me', { params: { feature }, headers: { 'X-Silent': '1' } })
  },
}
