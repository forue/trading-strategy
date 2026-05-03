<template>
  <div class="app-container">
    <!-- 侧边栏 -->
    <div class="sidebar">
      <div class="logo">
        <el-icon class="logo-icon"><TrendCharts /></el-icon>
        <span>轮动策略</span>
      </div>
      <el-menu
        :default-active="currentRoute"
        router
        background="transparent"
        text-color="rgba(255,255,255,0.7)"
        active-text-color="#fff"
      >
        <el-menu-item index="/">
          <el-icon><DataBoard /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/strategy">
          <el-icon><Setting /></el-icon>
          <span>策略管理</span>
        </el-menu-item>
        <el-menu-item index="/signals">
          <el-icon><Bell /></el-icon>
          <span>交易信号</span>
        </el-menu-item>
        <el-menu-item index="/fund">
          <el-icon><Wallet /></el-icon>
          <span>资金管理</span>
        </el-menu-item>
        <el-menu-item index="/monitor">
          <el-icon><Monitor /></el-icon>
          <span>系统监控</span>
        </el-menu-item>
        <el-menu-item index="/data-replay">
          <el-icon><VideoPlay /></el-icon>
          <span>数据回放</span>
        </el-menu-item>
        <el-menu-item index="/factor-analysis">
          <el-icon><Histogram /></el-icon>
          <span>因子分析</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Tools /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
      </el-menu>
    </div>

    <!-- 主内容区 -->
    <div class="main-content">
      <div class="header">
        <div class="header-left">
          <span>{{ currentPageTitle }}</span>
        </div>
        <div class="header-right">
          <el-badge :is-dot="signalStore.currentSignals.length > 0" class="signal-badge">
            <el-icon :size="20"><Bell /></el-icon>
          </el-badge>
          <el-tooltip content="AI 投研助手" placement="bottom">
            <el-button :icon="ChatDotRound" circle size="small" @click="toggleAiSidebar" />
          </el-tooltip>
          <el-dropdown @command="handleCommand">
            <span class="user-info">
              <el-icon><User /></el-icon>
              {{ userStore.userInfo?.username || '用户' }}
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
      <div class="page-content">
        <router-view />
      </div>
    </div>

    <!-- AI 助手侧边栏 -->
    <div class="ai-sidebar" :class="{ open: aiSidebarOpen }">
      <div class="ai-sidebar-header">
        <span>AI 投研助手</span>
        <el-button :icon="Close" circle size="small" @click="aiSidebarOpen = false" />
      </div>
      <div class="ai-sidebar-content">
        <ChatAssistant />
      </div>
    </div>

    <!-- AI 侧边栏遮罩 -->
    <div class="ai-sidebar-mask" :class="{ visible: aiSidebarOpen }" @click="aiSidebarOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound, Close } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useSignalStore } from '@/stores/signal'
import ChatAssistant from '@/components/ChatAssistant.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const signalStore = useSignalStore()

const currentRoute = computed(() => route.path)
const currentPageTitle = computed(() => (route.meta.title as string) || '仪表盘')

const aiSidebarOpen = ref(false)

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

<style lang="scss">
.app-container {
  display: flex;
  height: 100vh;
  overflow: hidden;
  position: relative;
}

.sidebar {
  width: 200px;
  min-width: 200px;
  background: #1f2d3d;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.header {
  height: 50px;
  line-height: 50px;
  padding: 0 20px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-content {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
  background: #f5f7fa;
}

// AI 助手侧边栏
.ai-sidebar {
  position: fixed;
  top: 0;
  right: 0;
  width: 420px;
  height: 100vh;
  background: #fff;
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.08);
  z-index: 1001;
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  will-change: transform;

  &.open {
    transform: translateX(0);
  }

  .ai-sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid #e4e7ed;
    font-weight: 600;
    font-size: 15px;
    background: #f5f7fa;
  }

  .ai-sidebar-content {
    flex: 1;
    overflow: hidden;

    .chat-assistant {
      height: 100%;
      border: none;
      border-radius: 0;
    }
  }
}

.ai-sidebar-mask {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0);
  z-index: 1000;
  pointer-events: none;
  transition: background 0.3s cubic-bezier(0.4, 0, 0.2, 1);

  &.visible {
    background: rgba(0, 0, 0, 0.35);
    pointer-events: auto;
  }
}

@media (max-width: 768px) {
  .sidebar {
    width: 60px;
    min-width: 60px;
    .logo span { display: none; }
    .el-menu-item span { display: none; }
  }

  .ai-sidebar {
    width: 100%;
    right: -100%;
  }
}

@media (max-width: 480px) {
  .sidebar { display: none; }
}
</style>
