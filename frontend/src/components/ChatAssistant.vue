<template>
  <div class="chat-assistant">
    <!-- 顶部工具栏 -->
    <div class="chat-toolbar">
      <el-button :icon="Plus" size="small" @click="newConversation">新对话</el-button>
      <el-select v-model="currentConvId" size="small" style="flex: 1" placeholder="选择对话" @change="switchConversation">
        <el-option v-for="c in conversations" :key="c.id" :label="c.title" :value="c.id">
          <span>{{ c.title }}</span>
          <span style="float: right; color: #8492a6; font-size: 11px">{{ c.message_count }}条</span>
        </el-option>
      </el-select>
      <el-dropdown @command="handleConvAction" trigger="click">
        <el-button :icon="MoreFilled" size="small" circle />
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="share"><el-icon><Share /></el-icon> 分享图片</el-dropdown-item>
            <el-dropdown-item command="export_md"><el-icon><Document /></el-icon> 导出 Markdown</el-dropdown-item>
            <el-dropdown-item command="delete" divided><el-icon><Delete /></el-icon> 删除对话</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <!-- 模型选择 -->
    <div class="model-bar">
      <el-select v-model="chatProvider" size="small" style="width: 110px" @change="onProviderChange">
        <el-option v-for="p in availableProviders" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-select v-model="chatModel" size="small" style="flex: 1" filterable allow-create>
        <el-option v-for="m in currentModels" :key="m.value" :label="m.label" :value="m.value">
          <span>{{ m.label }}</span>
          <span v-if="m.desc" style="float: right; color: #8492a6; font-size: 11px">{{ m.desc }}</span>
        </el-option>
      </el-select>
    </div>

    <!-- 消息列表 -->
    <div class="chat-messages" ref="messagesRef">
      <div v-if="currentMessages.length === 0" class="welcome">
        <div class="welcome-icon">🤖</div>
        <div class="welcome-text">AI 投研助手</div>
        <div class="welcome-hint">分析板块 · 解读信号 · 风险预警</div>
        <div class="quick-questions">
          <el-button v-for="q in quickQuestions" :key="q.text" size="small" @click="handleQuickQuestion(q)">
            {{ q.text }}
          </el-button>
        </div>
      </div>

      <div v-for="(msg, idx) in currentMessages" :key="idx" class="message" :class="msg.role" :id="`msg-${idx}`">
        <div class="avatar">
          <el-icon v-if="msg.role === 'user'"><User /></el-icon>
          <span v-else>🤖</span>
        </div>
        <div class="content">
          <div v-if="msg.role === 'user'" class="text user-text">{{ msg.content }}</div>
          <div v-else class="text md-body" v-html="renderMarkdown(msg.content)"></div>
          <div v-if="msg.role === 'assistant' && msg.model" class="meta">
            {{ msg.model }} | {{ msg.tokens_used }} tokens
          </div>
        </div>
      </div>

      <div v-if="sending" class="message assistant">
        <div class="avatar">🤖</div>
        <div class="content">
          <div class="typing"><span></span><span></span><span></span></div>
        </div>
      </div>
    </div>

    <!-- 快捷功能 -->
    <div class="quick-actions">
      <el-tag v-for="action in quickActions" :key="action.text" size="small" class="action-tag" @click="handleQuickQuestion(action)">
        {{ action.icon }} {{ action.text }}
      </el-tag>
    </div>

    <!-- 输入框 -->
    <div class="chat-input">
      <el-input
        v-model="inputText"
        type="textarea"
        :rows="2"
        placeholder="输入问题... (Enter 发送, Shift+Enter 换行)"
        :disabled="sending"
        @keydown="handleKeydown"
      />
      <el-button class="send-btn" :icon="Promotion" type="primary" @click="handleSend" :loading="sending" :disabled="!inputText.trim()">
        发送
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { Plus, MoreFilled, Delete, Document, Share, User, Promotion } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { aiApi } from '@/api/ai'
import type { Conversation, ChatMessage, ProviderConfig } from '@/api/ai'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
})

interface QuickAction {
  icon: string
  text: string
  command: string
}

const quickQuestions: QuickAction[] = [
  { icon: '📊', text: '今日市场分析', command: 'market_analysis' },
  { icon: '📈', text: '今日交易信号', command: 'today_signals' },
  { icon: '⚠️', text: '风险检查', command: 'risk_check' },
  { icon: '🔄', text: '板块轮动分析', command: 'sector_rotation' },
]

const quickActions: QuickAction[] = [
  { icon: '🏦', text: '银行板块分析', command: 'analyze_sector:银行' },
  { icon: '💊', text: '医药板块分析', command: 'analyze_sector:医药' },
  { icon: '💻', text: '科技板块分析', command: 'analyze_sector:科技' },
  { icon: '⚡', text: '新能源分析', command: 'analyze_sector:新能源' },
]

const availableProviders = ref<ProviderConfig[]>([])
const conversations = ref<Conversation[]>([])
const currentConvId = ref('')
const currentMessages = ref<ChatMessage[]>([])
const inputText = ref('')
const sending = ref(false)
const messagesRef = ref<HTMLElement>()
const chatProvider = ref('deepseek')
const chatModel = ref('deepseek-chat')

const currentModels = computed(() => {
  const p = availableProviders.value.find(p => p.id === chatProvider.value)
  return p?.models || []
})

onMounted(async () => {
  await loadProviders()
  await loadConversations()
})

async function loadProviders() {
  try {
    availableProviders.value = await aiApi.listProviders(true)
    if (availableProviders.value.length > 0) {
      const first = availableProviders.value[0]
      chatProvider.value = first.id
      if (first.models.length > 0) {
        chatModel.value = first.models[0].value
      }
    }
  } catch {
    availableProviders.value = []
  }
}

function onProviderChange(providerId: string) {
  const p = availableProviders.value.find(p => p.id === providerId)
  if (p && p.models.length > 0) {
    chatModel.value = p.models[0].value
  }
}

async function loadConversations() {
  try {
    conversations.value = await aiApi.listConversations()
    if (conversations.value.length > 0 && !currentConvId.value) {
      switchConversation(conversations.value[0].id)
    }
  } catch {
    conversations.value = []
  }
}

async function switchConversation(convId: string) {
  if (!convId) return
  currentConvId.value = convId
  try {
    const conv = await aiApi.getConversation(convId)
    currentMessages.value = conv.messages || []
    await scrollToBottom()
  } catch {
    currentMessages.value = []
  }
}

function newConversation() {
  currentConvId.value = ''
  currentMessages.value = []
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

async function handleQuickQuestion(action: QuickAction) {
  let message = ''
  switch (action.command) {
    case 'market_analysis':
      message = '帮我分析一下今天的市场整体情况，包括大盘走势、板块轮动、资金流向'
      break
    case 'today_signals':
      message = '查询今天的交易信号，分析各个策略的信号情况'
      break
    case 'risk_check':
      message = '帮我检查一下当前投资组合的风险状况'
      break
    case 'sector_rotation':
      message = '分析一下最近的板块轮动趋势，哪些板块在流入资金，哪些在流出'
      break
    default:
      if (action.command.startsWith('analyze_sector:')) {
        const sector = action.command.split(':')[1]
        message = `帮我详细分析一下${sector}板块的近期走势、资金流向、估值情况，以及未来的投资机会和风险`
      }
  }
  if (message) {
    inputText.value = message
    await handleSend()
  }
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  currentMessages.value.push({
    role: 'user',
    content: text,
    model: '',
    tokens_used: 0,
    timestamp: new Date().toISOString(),
  })
  inputText.value = ''
  sending.value = true
  await scrollToBottom()

  try {
    const res = await aiApi.chat(text, currentConvId.value, chatProvider.value, chatModel.value)
    currentConvId.value = res.conversation_id
    currentMessages.value.push({
      role: 'assistant',
      content: res.reply,
      model: res.model,
      tokens_used: res.tokens_used,
      timestamp: new Date().toISOString(),
    })
    await loadConversations()
  } catch (e: any) {
    currentMessages.value.push({
      role: 'assistant',
      content: `处理失败: ${e?.message || '未知错误'}`,
      model: '',
      tokens_used: 0,
      timestamp: new Date().toISOString(),
    })
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

async function handleConvAction(command: string) {
  if (!currentConvId.value) {
    ElMessage.warning('请先选择或创建一个对话')
    return
  }
  switch (command) {
    case 'share':
      await shareAsImage()
      break
    case 'export_md':
      await exportChat()
      break
    case 'delete':
      await deleteChat()
      break
  }
}

async function shareAsImage() {
  try {
    const { default: html2canvas } = await import('html2canvas')
    const el = messagesRef.value
    if (!el) return
    const canvas = await html2canvas(el, { backgroundColor: '#fff', scale: 2, useCORS: true })
    canvas.toBlob(async (blob) => {
      if (!blob) return
      try {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
        ElMessage.success('已复制到剪贴板')
      } catch {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `chat_${currentConvId.value.slice(-8)}.png`
        a.click()
        URL.revokeObjectURL(url)
        ElMessage.success('图片已下载')
      }
    })
  } catch (e: any) {
    ElMessage.error('生成图片失败')
  }
}

async function exportChat() {
  try {
    const content = await aiApi.exportConversation(currentConvId.value, 'markdown')
    const conv = conversations.value.find(c => c.id === currentConvId.value)
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${conv?.title || '对话'}.md`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  }
}

async function deleteChat() {
  try {
    await ElMessageBox.confirm('确定删除此对话？', '提示', { type: 'warning' })
    await aiApi.deleteConversation(currentConvId.value)
    ElMessage.success('对话已删除')
    currentConvId.value = ''
    currentMessages.value = []
    await loadConversations()
  } catch {}
}

function renderMarkdown(text: string): string {
  return md.render(text)
}

async function scrollToBottom() {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}
</script>

<style lang="scss" scoped>
.chat-assistant {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;

  .chat-toolbar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 14px;
    border-bottom: 1px solid #ebeef5;
    background: #fafafa;
  }

  .model-bar {
    display: flex;
    gap: 6px;
    padding: 8px 14px;
    border-bottom: 1px solid #ebeef5;
  }

  .chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px;

    .welcome {
      text-align: center;
      padding: 40px 16px;
      .welcome-icon { font-size: 48px; margin-bottom: 12px; }
      .welcome-text { font-size: 18px; font-weight: 600; margin-bottom: 6px; }
      .welcome-hint { font-size: 13px; color: #909399; margin-bottom: 20px; }
      .quick-questions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }
    }

    .message {
      display: flex;
      gap: 12px;
      margin-bottom: 20px;
      &.user {
        flex-direction: row-reverse;
        .avatar { background: #409eff; color: #fff; }
        .content { align-items: flex-end; }
      }
      .avatar {
        flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%;
        background: #f0f2f5; display: flex; align-items: center; justify-content: center; font-size: 16px;
      }
      .content {
        display: flex; flex-direction: column; max-width: 80%;
        .user-text {
          padding: 10px 14px; background: #ecf5ff; border-radius: 12px 12px 2px 12px;
          font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
        }
        .md-body {
          padding: 12px 16px; background: #f5f7fa; border-radius: 12px 12px 12px 2px;
          font-size: 14px; line-height: 1.7; word-break: break-word;

          :deep(p) { margin: 0 0 10px 0; &:last-child { margin-bottom: 0; } }
          :deep(h1), :deep(h2), :deep(h3) { margin: 16px 0 8px 0; font-weight: 600; }
          :deep(h1) { font-size: 18px; }
          :deep(h2) { font-size: 16px; }
          :deep(h3) { font-size: 15px; }
          :deep(ul), :deep(ol) { margin: 8px 0; padding-left: 20px; }
          :deep(li) { margin: 4px 0; }
          :deep(code) {
            background: #e6e8eb; padding: 2px 5px; border-radius: 4px;
            font-family: 'Consolas', 'Monaco', monospace; font-size: 13px;
          }
          :deep(pre) {
            background: #1e1e1e; color: #d4d4d4; padding: 12px 16px; border-radius: 8px;
            overflow-x: auto; margin: 10px 0;
            code { background: none; padding: 0; color: inherit; }
          }
          :deep(blockquote) {
            border-left: 3px solid #409eff; padding-left: 12px; margin: 8px 0;
            color: #606266;
          }
          :deep(table) {
            border-collapse: collapse; margin: 10px 0; width: 100%;
            th, td { border: 1px solid #e4e7ed; padding: 6px 10px; text-align: left; }
            th { background: #f5f7fa; font-weight: 600; }
          }
          :deep(a) { color: #409eff; text-decoration: none; }
          :deep(hr) { border: none; border-top: 1px solid #e4e7ed; margin: 12px 0; }
          :deep(strong) { font-weight: 600; }
        }
        .meta { font-size: 11px; color: #c0c4cc; margin-top: 4px; }
      }
      .typing {
        display: flex; gap: 4px; padding: 12px 16px; background: #f5f7fa; border-radius: 12px;
        span {
          width: 6px; height: 6px; background: #c0c4cc; border-radius: 50%; animation: typing 1.4s infinite;
          &:nth-child(2) { animation-delay: 0.2s; }
          &:nth-child(3) { animation-delay: 0.4s; }
        }
      }
    }
  }

  .quick-actions {
    display: flex;
    gap: 6px;
    padding: 8px 14px;
    border-top: 1px solid #ebeef5;
    overflow-x: auto;
    .action-tag {
      cursor: pointer; white-space: nowrap; transition: background 0.2s;
      &:hover { background: #ecf5ff; }
    }
  }

  .chat-input {
    padding: 12px 14px;
    border-top: 1px solid #ebeef5;
    display: flex;
    gap: 8px;
    align-items: flex-end;

    :deep(.el-textarea__inner) {
      resize: none;
      border-radius: 8px;
    }
    .send-btn {
      height: 56px;
      border-radius: 8px;
    }
  }
}

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-4px); }
}
</style>
