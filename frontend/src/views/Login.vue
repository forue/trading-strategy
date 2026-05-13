<template>
  <div class="login-page">
    <!-- Animated background -->
    <div class="login-bg">
      <div class="bg-orb bg-orb--1" />
      <div class="bg-orb bg-orb--2" />
      <div class="bg-orb bg-orb--3" />
    </div>

    <div class="login-card">
      <div class="login-brand">
        <div class="brand-icon">
          <el-icon :size="36"><TrendCharts /></el-icon>
        </div>
        <h1 class="brand-title">A股轮动策略交易系统</h1>
        <p class="brand-subtitle">板块资金轮动 · 三档策略信号 · 智能监控推送</p>
      </div>

      <el-tabs v-model="activeTab" class="login-tabs" :stretch="true">
        <el-tab-pane label="登录" name="login">
          <el-form
            ref="loginFormRef"
            :model="loginForm"
            :rules="loginRules"
            label-width="0"
            size="large"
            @keyup.enter="handleLogin"
          >
            <el-form-item prop="username">
              <el-input
                v-model="loginForm.username"
                placeholder="用户名"
                :prefix-icon="User"
              />
            </el-form-item>
            <el-form-item prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                placeholder="密码"
                :prefix-icon="Lock"
                show-password
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="large" :loading="loading" style="width: 100%; height: 44px" @click="handleLogin">
                {{ loading ? '登录中...' : '登 录' }}
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-form
            ref="registerFormRef"
            :model="registerForm"
            :rules="registerRules"
            label-width="0"
            size="large"
          >
            <el-form-item prop="username">
              <el-input
                v-model="registerForm.username"
                placeholder="用户名"
                :prefix-icon="User"
              />
            </el-form-item>
            <el-form-item prop="email">
              <el-input
                v-model="registerForm.email"
                placeholder="邮箱"
                :prefix-icon="Message"
              />
            </el-form-item>
            <el-form-item prop="password">
              <el-input
                v-model="registerForm.password"
                type="password"
                placeholder="密码（至少6位）"
                :prefix-icon="Lock"
                show-password
              />
            </el-form-item>
            <el-form-item prop="confirmPassword">
              <el-input
                v-model="registerForm.confirmPassword"
                type="password"
                placeholder="确认密码"
                :prefix-icon="Lock"
                show-password
                @keyup.enter="handleRegister"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="large" :loading="loading" style="width: 100%; height: 44px" @click="handleRegister">
                {{ loading ? '注册中...' : '注 册' }}
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <!-- Theme toggle -->
      <div class="login-footer">
        <button class="theme-switch" @click="theme.toggle()">
          <el-icon :size="14"><Sunny v-if="theme.mode === 'dark'" /><Moon v-else /></el-icon>
          <span>{{ theme.mode === 'light' ? '深色模式' : '浅色模式' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Message } from '@element-plus/icons-vue'
import type { FormInstance } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'

const router = useRouter()
const userStore = useUserStore()
const theme = useThemeStore()

const activeTab = ref('login')
const loading = ref(false)
const loginFormRef = ref<FormInstance>()
const registerFormRef = ref<FormInstance>()

const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({ username: '', email: '', password: '', confirmPassword: '' })

const loginRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const registerRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email' as const, message: '请输入正确的邮箱格式', trigger: 'blur' },
  ],
  password: [{ required: true, min: 6, message: '密码至少6位', trigger: 'blur' }],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: any) => {
        if (value !== registerForm.password) callback(new Error('两次密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

async function handleLogin() {
  try {
    await loginFormRef.value?.validate()
  } catch {
    return // 校验失败，表单已显示错误提示
  }
  loading.value = true
  try {
    await userStore.login(loginForm)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (e: any) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  await registerFormRef.value?.validate()
  loading.value = true
  try {
    const { authApi } = await import('@/api/auth')
    await authApi.register({
      username: registerForm.username,
      password: registerForm.password,
      email: registerForm.email,
    })
    ElMessage.success('注册成功，请登录')
    activeTab.value = 'login'
    loginForm.username = registerForm.username
  } catch (e: any) {
    ElMessage.error(e.message || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  position: relative;
  overflow: hidden;
}

/* Animated background orbs */
.login-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.3;
  animation: orb-float 20s ease-in-out infinite;

  &--1 {
    width: 500px;
    height: 500px;
    background: var(--accent-primary);
    top: -150px;
    right: -100px;
    animation-delay: 0s;
  }
  &--2 {
    width: 400px;
    height: 400px;
    background: var(--accent-success);
    bottom: -100px;
    left: -80px;
    animation-delay: -7s;
  }
  &--3 {
    width: 300px;
    height: 300px;
    background: var(--accent-warning);
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    animation-delay: -14s;
    opacity: 0.15;
  }
}

@keyframes orb-float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  25% { transform: translate(30px, -40px) scale(1.1); }
  50% { transform: translate(-20px, 20px) scale(0.95); }
  75% { transform: translate(-40px, -10px) scale(1.05); }
}

/* Card */
.login-card {
  position: relative;
  width: 420px;
  max-width: calc(100vw - 32px);
  background: var(--bg-secondary);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-lg);
  padding: 36px 32px 24px;
  box-shadow: var(--shadow-modal);
  z-index: 1;
  backdrop-filter: blur(10px);
}

/* Brand */
.login-brand {
  text-align: center;
  margin-bottom: 28px;

  .brand-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 64px;
    height: 64px;
    border-radius: var(--radius-md);
    background: var(--accent-primary-light);
    color: var(--accent-primary);
    margin-bottom: 16px;
  }

  .brand-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0 0 6px;
    letter-spacing: 0.5px;
  }

  .brand-subtitle {
    font-size: 13px;
    color: var(--text-tertiary);
    margin: 0;
  }
}

/* Tabs */
.login-tabs {
  :deep(.el-tabs__header) {
    margin-bottom: 20px;
  }
  :deep(.el-tabs__item) {
    font-size: 14px;
    font-weight: 500;
  }
}

/* Form */
:deep(.el-input__wrapper) {
  border-radius: var(--radius-sm);
  background: var(--bg-tertiary);
  transition: all var(--transition-fast);
}
:deep(.el-input__wrapper:focus-within),
:deep(.el-input__wrapper:hover) {
  background: var(--bg-secondary);
}

/* Footer */
.login-footer {
  display: flex;
  justify-content: center;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border-subtle);
}

.theme-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-primary);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: 12px;
  font-family: var(--font-sans);

  &:hover {
    border-color: var(--accent-primary);
    color: var(--accent-primary);
    background: var(--accent-primary-light);
  }
}

@media (max-width: 480px) {
  .login-card { padding: 24px 16px 16px; }
  .login-brand .brand-icon { width: 48px; height: 48px; margin-bottom: 8px; }
  .bg-orbs .bg-orb { display: none; }
}
</style>
