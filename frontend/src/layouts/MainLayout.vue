<template>
  <div class="app-container">
    <!-- 侧栏：默认展开显示全部 11 项，可折叠为 60px 图标轨 -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }" aria-label="主导航">
      <div class="side-logo">
        <div class="logo-mark" title="点击展开 / 收起导航" @click="sidebarCollapsed = !sidebarCollapsed">LS</div>
        <span class="logo-text">轮动策略</span>
        <button
          class="collapse-btn"
          :title="sidebarCollapsed ? '展开导航' : '收起导航'"
          :aria-label="sidebarCollapsed ? '展开导航' : '收起导航'"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <el-icon :size="16"><Fold v-if="!sidebarCollapsed" /><Expand v-else /></el-icon>
        </button>
      </div>

      <nav class="side-nav">
        <template v-for="group in navGroups" :key="group.label">
          <div class="side-group-label">{{ group.label }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="side-item"
            :class="{ 'is-active': currentRoute === item.path }"
            :title="item.label"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </router-link>
        </template>
      </nav>

    </aside>

    <div class="main-content">
      <header class="page-context">
        <div class="context-left">
          <h1>{{ currentPageTitle }}</h1>
          <p class="context-sub">全局策略视图 · 所有页面按所选策略刷新</p>
        </div>
        <div class="context-actions">
          <el-tooltip content="全局策略：切换后各页面按所选策略刷新" placement="bottom">
            <el-select v-model="strategyStore.currentStrategy" size="small" class="context-strategy-select">
              <el-option v-for="o in STRATEGY_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
          </el-tooltip>

          <button
            class="context-icon"
            :title="theme.mode === 'light' ? '切换深色模式' : '切换浅色模式'"
            :aria-label="theme.mode === 'light' ? '切换深色模式' : '切换浅色模式'"
            @click="theme.toggle()"
          >
            <el-icon :size="18"><Sunny v-if="theme.mode === 'dark'" /><Moon v-else /></el-icon>
          </button>

          <el-badge :is-dot="signalStore.currentSignals.length > 0">
            <button class="context-icon" title="交易信号" aria-label="交易信号" @click="viewSignals">
              <el-icon :size="18"><Bell /></el-icon>
            </button>
          </el-badge>

          <button class="context-icon" title="AI 投研助手" aria-label="AI 投研助手" @click="toggleAiSidebar">
            <el-icon :size="18"><ChatDotRound /></el-icon>
          </button>

          <el-dropdown @command="handleCommand" trigger="click">
            <button class="user-btn" title="用户菜单" aria-label="用户菜单">
              <el-icon :size="16"><User /></el-icon>
              <span class="user-name">{{ userStore.userInfo?.username || '用户' }}</span>
              <el-icon :size="12"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">
                  <el-icon><SwitchButton /></el-icon>
                  <span>退出登录</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="page-content">
        <router-view />
      </main>
    </div>

    <!-- 移动端：56px 底部标签栏 -->
    <nav class="bottom-tabs" aria-label="移动端导航">
      <router-link
        v-for="item in bottomItems"
        :key="item.path"
        :to="item.path"
        class="bottom-tab"
        :class="{ 'is-active': currentRoute === item.path }"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.short }}</span>
      </router-link>
      <button class="bottom-tab" aria-label="更多功能" @click="moreOpen = true">
        <el-icon><More /></el-icon>
        <span>更多</span>
      </button>
    </nav>

    <!-- 移动端「更多」抽屉：包含全部 11 项，无功能缺失 -->
    <el-drawer v-model="moreOpen" direction="btt" size="auto" :with-header="false" class="mobile-more-drawer">
      <div class="more-title">全部功能</div>
      <div class="more-grid">
        <router-link
          v-for="item in allNavItems"
          :key="item.path"
          :to="item.path"
          class="more-item"
          :class="{ 'is-active': currentRoute === item.path }"
          @click="moreOpen = false"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </div>
    </el-drawer>

    <!-- AI 浮层：桌面 640px / 移动全屏（宽度不可压缩，避免图表显示不完整） -->
    <div class="ai-sidebar" :class="{ open: aiSidebarOpen }">
      <div class="ai-sidebar-header">
        <span>AI 投研助手</span>
        <button class="btn-ghost" aria-label="关闭 AI 助手" @click="aiSidebarOpen = false">
          <el-icon :size="16"><Close /></el-icon>
        </button>
      </div>
      <div class="ai-sidebar-content">
        <ChatAssistant />
      </div>
    </div>
    <div class="ai-sidebar-mask" :class="{ visible: aiSidebarOpen }" @click="aiSidebarOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatDotRound, Close, Sunny, Moon, Bell, More, SwitchButton, Fold, Expand, User, ArrowDown,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useSignalStore } from '@/stores/signal'
import { useThemeStore } from '@/stores/theme'
import { useStrategyStore, STRATEGY_OPTIONS } from '@/stores/strategy'
import ChatAssistant from '@/components/ChatAssistant.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const signalStore = useSignalStore()
const theme = useThemeStore()
const strategyStore = useStrategyStore()

const currentRoute = computed(() => route.path)
const currentPageTitle = computed(() => (route.meta.title as string) || '仪表盘')

const sidebarCollapsed = ref(false)
const moreOpen = ref(false)
const aiSidebarOpen = ref(false)

watch(() => route.path, () => { moreOpen.value = false })

// 全部 11 项，按业务域分组，一项不砍
const navGroups = [
  {
    label: '工作台',
    items: [
      { path: '/', label: '仪表盘', short: '仪表盘', icon: 'DataBoard' },
    ],
  },
  {
    label: '策略与交易',
    items: [
      { path: '/strategy', label: '策略管理', short: '策略', icon: 'Setting' },
      { path: '/signals', label: '交易信号', short: '信号', icon: 'Bell' },
      { path: '/fund', label: '资金管理', short: '资金', icon: 'Wallet' },
    ],
  },
  {
    label: '复盘与分析',
    items: [
      { path: '/review', label: '策略复盘', short: '复盘', icon: 'DataAnalysis' },
      { path: '/factor-analysis', label: '因子分析', short: '因子', icon: 'Histogram' },
      { path: '/factor-ranking', label: '板块因子排名', short: '排名', icon: 'Histogram' },
      { path: '/data-replay', label: '数据回放', short: '回放', icon: 'VideoPlay' },
      { path: '/stock-sense', label: '盘感训练', short: '盘感', icon: 'TrendCharts' },
    ],
  },
  {
    label: '系统',
    items: [
      { path: '/monitor', label: '系统监控', short: '监控', icon: 'Monitor' },
      { path: '/settings', label: '系统设置', short: '设置', icon: 'Tools' },
    ],
  },
]

const allNavItems = navGroups.flatMap(group => group.items)
const bottomItems = allNavItems.filter(item =>
  ['/', '/signals', '/review', '/fund'].includes(item.path)
)

function toggleAiSidebar() {
  aiSidebarOpen.value = !aiSidebarOpen.value
}

function viewSignals() {
  signalStore.clearSignals()
  router.push('/signals')
}

function handleCommand(command: string) {
  if (command === 'logout') {
    userStore.logout()
    signalStore.disconnectWebSocket()
    router.push('/login')
  }
}

onMounted(() => {
  signalStore.connectWebSocket()
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission()
  }
})

onUnmounted(() => {
  signalStore.disconnectWebSocket()
})
</script>

<style lang="scss" scoped>
.context-strategy-select {
  width: 130px;
  margin-right: 4px;
}

.user-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px 5px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-primary);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  font-size: 13px;
  font-family: var(--font-sans);

  &:hover {
    background: var(--bg-hover);
    border-color: var(--accent-primary);
    color: var(--accent-primary);
  }

  .user-name {
    max-width: 100px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.mobile-more-drawer {
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;

  :deep(.el-drawer__body) {
    padding: 20px 16px 32px;
  }

  .more-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: 16px;
  }

  .more-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px 8px;
  }

  .more-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 12px 4px;
    min-height: 60px;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 11px;
    text-align: center;

    .el-icon { font-size: 20px; }

    &.is-active {
      background: var(--bg-active);
      color: var(--accent-primary);
    }
  }
}

@media (max-width: 768px) {
  .user-btn .user-name { display: none; }
}

@media (max-width: 480px) {
  .context-strategy-select { width: 110px; }
  .more-grid { grid-template-columns: repeat(3, 1fr); }
}
</style>
