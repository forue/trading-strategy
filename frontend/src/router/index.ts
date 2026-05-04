import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

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
        path: 'signals',
        name: 'Signals',
        component: () => import('@/views/Signals.vue'),
        meta: { title: '交易信号', icon: 'Bell' },
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
        meta: { title: '系统监控', icon: 'Monitor' },
      },
      {
        path: 'data-replay',
        name: 'DataReplay',
        component: () => import('@/views/DataReplay.vue'),
        meta: { title: '数据回放', icon: 'VideoPlay' },
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
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth !== false && !token) {
    next({ name: 'Login' })
  } else {
    next()
  }
  document.title = `${to.meta.title || 'A股轮动策略'} - 轮动策略交易系统`
})

export default router
