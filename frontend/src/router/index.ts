import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { usePermissionStore } from '@/stores/permission'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '仪表盘', icon: 'DataBoard' },
      },
      {
        path: 'strategy',
        name: 'Strategy',
        component: () => import('@/views/Strategy.vue'),
        meta: { title: '策略管理', icon: 'Setting' },
      },
      {
        path: 'strategy-workshop',
        name: 'StrategyWorkshop',
        component: () => import('@/views/StrategyWorkshop.vue'),
        meta: { title: '策略工坊', icon: 'MagicStick' },
      },
      {
        path: 'signals',
        name: 'Signals',
        component: () => import('@/views/Signals.vue'),
        meta: { title: '交易信号', icon: 'Bell' },
      },
      {
        path: 'review',
        name: 'Review',
        component: () => import('@/views/Review.vue'),
        meta: { title: '策略复盘', icon: 'DataAnalysis' },
      },
      {
        path: 'fund',
        name: 'Fund',
        component: () => import('@/views/Fund.vue'),
        meta: { title: '资金管理', icon: 'Wallet' },
      },
      {
        path: 'monitor',
        name: 'Monitor',
        component: () => import('@/views/Monitor.vue'),
        // 与 /admin/* 同款角色闸门：系统监控只对管理员开放，不依赖后端授权表兜底
        meta: { title: '系统监控', icon: 'Monitor', admin: true },
      },
      {
        path: 'data-replay',
        name: 'DataReplay',
        component: () => import('@/views/DataReplay.vue'),
        meta: { title: '数据回放', icon: 'VideoPlay' },
      },
      {
        path: 'stock-sense',
        name: 'StockSense',
        component: () => import('@/views/StockSense.vue'),
        meta: { title: '盘感训练', icon: 'TrendCharts' },
      },
      {
        path: 'factor-analysis',
        name: 'FactorAnalysis',
        component: () => import('@/views/FactorAnalysis.vue'),
        meta: { title: '因子分析', icon: 'Histogram' },
      },
      {
        path: 'factor-ranking',
        name: 'FactorRanking',
        component: () => import('@/views/FactorRanking.vue'),
        meta: { title: '板块因子排名', icon: 'Histogram' },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/Settings.vue'),
        meta: { title: '系统设置', icon: 'Tools' },
      },
      // 后台管理：meta.admin 额外的角色闸门，页面权限配置里也永远是「仅管理员」
      {
        path: 'admin/users',
        name: 'AdminUsers',
        component: () => import('@/views/admin/AccountAdmin.vue'),
        meta: { title: '账号管理', icon: 'User', admin: true },
      },
      {
        path: 'admin/permissions',
        name: 'AdminPermissions',
        component: () => import('@/views/admin/RoutePermission.vue'),
        meta: { title: '页面权限', icon: 'Lock', admin: true },
      },
      {
        path: 'admin/features',
        name: 'AdminFeatures',
        component: () => import('@/views/admin/FeatureQuota.vue'),
        meta: { title: '高级功能', icon: 'Operation', admin: true },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  document.title = `${to.meta.title || 'A股轮动策略'} - 轮动策略交易系统`

  if (to.meta.requiresAuth === false) {
    return true
  }

  const token = localStorage.getItem('token')
  if (!token) {
    // 未登录状态清掉上一次会话的权限缓存，避免换账号后沿用旧权限
    usePermissionStore().reset()
    return { name: 'Login' }
  }

  const permission = usePermissionStore()
  if (!permission.loaded) {
    await permission.fetchMine()
  }

  const denied = to.meta.admin ? !permission.isAdmin : !permission.can(to.path)
  if (denied) {
    const target = permission.firstAllowed()
    // 兜底：配置异常导致落点等于目标页时直接放行，避免路由死循环
    return target === to.path ? true : { path: target }
  }
  return true
})

export default router
