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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useSignalStore } from '@/stores/signal'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const signalStore = useSignalStore()

const currentRoute = computed(() => route.path)
const currentPageTitle = computed(() => (route.meta.title as string) || '仪表盘')

function handleCommand(command: string) {
  if (command === 'logout') {
    userStore.logout()
    signalStore.disconnectWebSocket()
    router.push('/login')
  }
}

onMounted(() => {
  signalStore.connectWebSocket()
  // 请求浏览器通知权限
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission()
  }
})

onUnmounted(() => {
  signalStore.disconnectWebSocket()
})
</script>
