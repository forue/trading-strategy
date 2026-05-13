<template>
  <div class="app-container">
    <!-- Sidebar Overlay (mobile) -->
    <div class="sidebar-overlay" :class="{ open: sidebarOpen }" @click="sidebarOpen = false" />

    <!-- Sidebar -->
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="logo">
        <el-icon class="logo-icon"><TrendCharts /></el-icon>
        <span class="logo-text">轮动策略</span>
        <button class="sidebar-close-btn" @click="sidebarOpen = false">
          <el-icon :size="18"><Close /></el-icon>
        </button>
      </div>
      <nav class="nav-menu">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ 'is-active': currentRoute === item.path }"
        >
          <span class="nav-icon"><el-icon><component :is="item.icon" /></el-icon></span>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <span class="version-badge">v2.0</span>
      </div>
    </aside>

    <!-- Main Content -->
    <div class="main-content">
      <header class="header">
        <div class="header-left">
          <button class="hamburger-btn" @click="sidebarOpen = !sidebarOpen">
            <el-icon :size="20"><component :is="sidebarOpen ? 'Close' : 'Expand'" /></el-icon>
          </button>
          <span class="header-dot" />
          <span>{{ currentPageTitle }}</span>
        </div>
        <div class="header-right">
          <!-- Theme Toggle -->
          <button class="btn-ghost" :title="theme.mode === 'light' ? '切换深色模式' : '切换浅色模式'" @click="theme.toggle()">
            <el-icon :size="18"><Sunny v-if="theme.mode === 'dark'" /><Moon v-else /></el-icon>
          </button>

          <!-- Signal Indicator -->
          <el-badge :is-dot="signalStore.currentSignals.length > 0" class="signal-badge">
            <button class="btn-ghost" title="交易信号" @click="signalStore.clearSignals(); router.push('/signals')">
              <el-icon :size="18"><Bell /></el-icon>
            </button>
          </el-badge>

          <!-- AI Assistant Toggle -->
          <el-tooltip content="AI 投研助手" placement="bottom">
            <button class="btn-ghost" @click="toggleAiSidebar">
              <el-icon :size="18"><ChatDotRound /></el-icon>
            </button>
          </el-tooltip>

          <!-- User Menu -->
          <el-dropdown @command="handleCommand" trigger="click">
            <button class="user-btn">
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

    <!-- AI Sidebar -->
    <div class="ai-sidebar" :class="{ open: aiSidebarOpen }">
      <div class="ai-sidebar-header">
        <span>AI 投研助手</span>
        <button class="btn-ghost" @click="aiSidebarOpen = false">
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
import { ChatDotRound, Close, Expand, SwitchButton } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useSignalStore } from '@/stores/signal'
import { useThemeStore } from '@/stores/theme'
import ChatAssistant from '@/components/ChatAssistant.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const signalStore = useSignalStore()
const theme = useThemeStore()

const currentRoute = computed(() => route.path)
const currentPageTitle = computed(() => (route.meta.title as string) || '仪表盘')

const sidebarOpen = ref(false)
const aiSidebarOpen = ref(false)

// Close mobile sidebar on route change
watch(() => route.path, () => { sidebarOpen.value = false })

const navItems = [
  { path: '/', label: '仪表盘', icon: 'DataBoard' },
  { path: '/strategy', label: '策略管理', icon: 'Setting' },
  { path: '/signals', label: '交易信号', icon: 'Bell' },
  { path: '/fund', label: '资金管理', icon: 'Wallet' },
  { path: '/monitor', label: '系统监控', icon: 'Monitor' },
  { path: '/data-replay', label: '数据回放', icon: 'VideoPlay' },
  { path: '/factor-analysis', label: '因子分析', icon: 'Histogram' },
  { path: '/factor-ranking', label: '板块因子排名', icon: 'Histogram' },
  { path: '/settings', label: '系统设置', icon: 'Tools' },
]

function toggleAiSidebar() {
  aiSidebarOpen.value = !aiSidebarOpen.value
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
.sidebar-footer {
  padding: 12px 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;

  .version-badge {
    font-size: 11px;
    color: var(--text-sidebar);
    opacity: 0.4;
    letter-spacing: 1px;
  }
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
  transition: all var(--transition-fast);
  font-size: 13px;
  font-family: var(--font-sans);

  &:hover {
    background: var(--bg-secondary);
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

.sidebar-close-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--text-sidebar);
  cursor: pointer;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
  &:hover { background: var(--bg-sidebar-hover); }
}

@media (max-width: 768px) {
  .sidebar-close-btn { display: flex; }
  .user-btn .user-name { display: none; }
}

@media (max-width: 480px) {
  .header-left .header-dot,
  .header-left > span { font-size: 13px; }
}
</style>
