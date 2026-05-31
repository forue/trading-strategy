<template>
  <div class="chat-assistant">
    <!-- 顶部工具栏 -->
    <div class="chat-toolbar">
      <el-button :icon="Plus" size="small" @click="newConversation" :disabled="sending">新对话</el-button>
      <el-select v-model="currentConvId" size="small" style="flex: 1" placeholder="选择对话" @change="switchConversation" :disabled="sending">
        <el-option v-for="c in conversations" :key="c.id" :label="c.title" :value="c.id">
          <span>{{ c.title }}</span>
          <span style="float: right; color: var(--text-tertiary); font-size: 11px">{{ c.message_count }}条</span>
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
      <el-select v-model="chatProvider" size="small" style="width: 110px" @change="onProviderChange" :disabled="sending">
        <el-option v-for="p in availableProviders" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-select v-model="chatModel" size="small" style="flex: 1" filterable allow-create @change="saveModelPref" :disabled="sending">
        <el-option v-for="m in currentModels" :key="m.value" :label="m.label" :value="m.value">
          <span>{{ m.label }}</span>
          <span v-if="m.desc" style="float: right; color: var(--text-tertiary); font-size: 11px">{{ m.desc }}</span>
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
          <el-button v-for="q in quickQuestions" :key="q.text" size="small" @click="handleQuickQuestion(q)" :disabled="sending">
            {{ q.text }}
          </el-button>
        </div>
      </div>

      <div v-for="(msg, idx) in currentMessages" :key="idx" class="message" :class="msg.role">
        <div class="avatar">
          <el-icon v-if="msg.role === 'user'"><User /></el-icon>
          <span v-else>🤖</span>
        </div>
        <div class="content">
          <div v-if="msg.role === 'user'" class="text user-text">{{ msg.content }}</div>
          <template v-else>
            <!-- 工具调用记录 -->
            <div v-if="msg.toolCalls && msg.toolCalls.length" class="tool-call-block">
              <div v-for="(tc, idx) in msg.toolCalls" :key="'htc-'+idx" class="tool-call-item">
                <div class="tool-call-header">
                  <span>🔧</span>
                  <span>调用工具: {{ tc.name }}</span>
                </div>
                <div v-if="tc.result" class="tool-call-result">
                  <pre>{{ formatToolResult(tc.result) }}</pre>
                </div>
              </div>
            </div>
            <!-- Thinking -->
            <div v-if="msg.thinking" class="thinking-block">
              <div class="thinking-header" @click="toggleThinking(idx)">
                <el-icon><CaretRight /></el-icon>
                <span>思考过程</span>
              </div>
              <div v-if="expandedThinking.has(idx)" class="thinking-content">
                {{ msg.thinking }}
              </div>
            </div>
            <div class="text md-body" v-html="renderMarkdown(msg.content)"></div>
          </template>
          <div v-if="msg.role === 'assistant' && msg.model" class="meta">
            {{ msg.model }} | {{ msg.tokens_used }} tokens
          </div>
        </div>
      </div>

      <!-- 流式输出 -->
      <div v-if="streamingActive" class="message assistant">
        <div class="avatar">🤖</div>
        <div class="content">
          <!-- 工具调用状态 -->
          <div v-for="(tc, idx) in streamingToolCalls" :key="'tc-'+idx" class="tool-call-block">
            <div class="tool-call-header">
              <span class="tool-spinner">🔧</span>
              <span>调用工具: {{ tc.name }}</span>
            </div>
            <div v-if="tc.result" class="tool-call-result">
              <pre>{{ formatToolResult(tc.result) }}</pre>
            </div>
            <div v-else class="tool-call-loading">获取数据中...</div>
          </div>

          <!-- Thinking -->
          <div v-if="streamingThinking" class="thinking-block expanded">
            <div class="thinking-header">
              <span class="thinking-spinner">⏳</span>
              <span>思考中...</span>
            </div>
            <div class="thinking-content">{{ streamingThinking }}</div>
          </div>

          <!-- 回复内容 -->
          <div v-if="streamingContent" class="text md-body" v-html="renderMarkdown(streamingContent)"></div>

          <!-- 加载中 -->
          <div v-if="!streamingContent && !streamingThinking && !streamingToolCalls.length" class="typing">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 快捷功能 -->
    <div class="quick-actions">
      <el-tag v-for="action in quickActions" :key="action.text" size="small" class="action-tag" @click="handleQuickQuestion(action)" :class="{ disabled: sending }">
        {{ action.icon }} {{ action.text }}
      </el-tag>
    </div>

    <!-- 输入框 -->
    <div class="chat-input">
      <el-input
        v-model="inputText"
        type="textarea"
        :rows="2"
        :placeholder="sending ? 'AI 正在回复中...' : '输入问题... (Enter 发送, Shift+Enter 换行)'"
        :disabled="sending"
        @keydown="handleKeydown"
      />
      <div class="input-actions">
        <el-button v-if="sending" type="danger" :icon="VideoPause" @click="abortRequest" size="small">
          停止
        </el-button>
        <el-button v-else class="send-btn" :icon="Promotion" type="primary" @click="handleSend" :disabled="!inputText.trim()">
          发送
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, reactive, watch } from 'vue'
import { Plus, MoreFilled, Delete, Document, Share, User, Promotion, CaretRight, VideoPause } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { aiApi } from '@/api/ai'
import { useAiStore } from '@/stores/ai'
import type { Conversation, ChatMessage, ProviderConfig } from '@/api/ai'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const aiStore = useAiStore()

interface QuickAction { icon: string; text: string; command: string }

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

const availableProviders = computed(() => aiStore.providers)
const conversations = ref<Conversation[]>([])
const currentConvId = ref('')
const currentMessages = ref<ChatMessage[]>([])
const inputText = ref('')
const sending = ref(false)
const messagesRef = ref<HTMLElement>()

// 从 store 恢复，或默认选第一个可用提供商
const chatProvider = ref('')
const chatModel = ref('')

// 初始化提供商和模型
function initProviderModel() {
  const providers = availableProviders.value
  if (!providers.length) return

  // 尝试恢复上次选择
  const savedProvider = aiStore.lastProvider
  const savedModel = aiStore.lastModel

  const matchedProvider = providers.find(p => p.id === savedProvider)
  if (matchedProvider) {
    chatProvider.value = matchedProvider.id
    const matchedModel = matchedProvider.models.find(m => m.value === savedModel)
    chatModel.value = matchedModel ? matchedModel.value : (matchedProvider.models[0]?.value || '')
  } else {
    // 默认选第一个可用提供商
    const first = providers[0]
    chatProvider.value = first.id
    chatModel.value = first.models[0]?.value || ''
  }
}

// 流式输出状态
const streamingActive = ref(false)
const streamingContent = ref('')
const streamingThinking = ref('')
const streamingToolCalls = ref<{name: string; arguments: any; result?: string}[]>([])

// 请求中断控制器
let abortController: AbortController | null = null

// Thinking 展开状态
const expandedThinking = reactive(new Set<number>())

const currentModels = computed(() => {
  const p = availableProviders.value.find(p => p.id === chatProvider.value)
  return p?.models || []
})

// 监听提供商和模型变化，自动保存
watch(chatProvider, (val) => {
  aiStore.setProvider(val, chatModel.value)
})
watch(chatModel, (val) => {
  aiStore.setProvider(chatProvider.value, val)
})

// 持久化会话状态到 sessionStorage
const STATE_KEY = 'ai_chat_state'

function saveState() {
  try {
    sessionStorage.setItem(STATE_KEY, JSON.stringify({
      convId: currentConvId.value,
      messages: currentMessages.value,
      provider: chatProvider.value,
      model: chatModel.value,
    }))
  } catch {}
}

function restoreState() {
  try {
    const raw = sessionStorage.getItem(STATE_KEY)
    if (raw) {
      const state = JSON.parse(raw)
      if (state.convId) currentConvId.value = state.convId
      if (state.messages?.length) currentMessages.value = state.messages
      if (state.provider) chatProvider.value = state.provider
      if (state.model) chatModel.value = state.model
    }
  } catch {}
}

// 消息变化时自动保存
watch(currentMessages, saveState, { deep: true })
watch(currentConvId, saveState)

onMounted(async () => {
  restoreState()
  await aiStore.loadProviders()
  initProviderModel()
  await loadConversations()
  if (currentConvId.value && currentMessages.value.length === 0) {
    await switchConversation(currentConvId.value)
  }
  await scrollToBottom()
})

function onProviderChange(providerId: string) {
  const p = availableProviders.value.find(p => p.id === providerId)
  if (p && p.models.length > 0) {
    chatModel.value = p.models[0].value
  }
}

function saveModelPref() {
  // watch 已处理
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
  if (!convId || sending.value) return
  currentConvId.value = convId
  try {
    const conv = await aiApi.getConversation(convId)
    currentMessages.value = conv.messages || []
    if (conv.provider) chatProvider.value = conv.provider
    if (conv.model) chatModel.value = conv.model
    await scrollToBottom()
  } catch {
    currentMessages.value = []
  }
}

function newConversation() {
  if (sending.value) return
  currentConvId.value = ''
  currentMessages.value = []
  sessionStorage.removeItem(STATE_KEY)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

async function handleQuickQuestion(action: QuickAction) {
  if (sending.value) return
  let message = ''
  switch (action.command) {
    case 'market_analysis': message = '帮我分析一下今天的市场整体情况'; break
    case 'today_signals': message = '查询今天的交易信号，分析各个策略的信号情况'; break
    case 'risk_check': message = '帮我检查一下当前投资组合的风险状况'; break
    case 'sector_rotation': message = '分析一下最近的板块轮动趋势'; break
    default:
      if (action.command.startsWith('analyze_sector:')) {
        message = `帮我详细分析一下${action.command.split(':')[1]}板块的近期走势、资金流向、估值情况`
      }
  }
  if (message) { inputText.value = message; await handleSend() }
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  currentMessages.value.push({
    role: 'user', content: text, model: '', tokens_used: 0, timestamp: new Date().toISOString(),
  })
  inputText.value = ''
  sending.value = true
  streamingActive.value = true
  streamingContent.value = ''
  streamingThinking.value = ''
  streamingToolCalls.value = []

  // 创建中断控制器
  abortController = new AbortController()

  await scrollToBottom()

  try {
    const response = await fetch('/api/ai/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
      },
      body: JSON.stringify({
        message: text,
        conversation_id: currentConvId.value,
        provider: chatProvider.value,
        model: chatModel.value,
      }),
      signal: abortController.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(`HTTP ${response.status}: ${errText}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('无法读取响应流')

    const decoder = new TextDecoder()
    let buffer = ''
    let convId = currentConvId.value
    let gotDone = false

    while (!gotDone) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const data = JSON.parse(line.slice(6))
          if (data.type === 'conversation_id') {
            convId = data.data
            currentConvId.value = convId
          } else if (data.type === 'thinking') {
            streamingThinking.value += data.data
          } else if (data.type === 'content') {
            streamingContent.value += data.data
          } else if (data.type === 'tool_call') {
            streamingToolCalls.value.push({ name: data.data.name, arguments: data.data.arguments })
          } else if (data.type === 'tool_result') {
            const last = streamingToolCalls.value[streamingToolCalls.value.length - 1]
            if (last) last.result = data.data.result
          } else if (data.type === 'error') {
            throw new Error(data.data)
          } else if (data.type === 'done') {
            gotDone = true
          }
          await scrollToBottom()
        } catch (e: any) {
          if (e.message && !e.message.includes('JSON')) throw e
        }
      }
    }

    if (streamingContent.value) {
      currentMessages.value.push({
        role: 'assistant',
        content: streamingContent.value,
        thinking: streamingThinking.value,
        toolCalls: streamingToolCalls.value.length > 0 ? [...streamingToolCalls.value] : undefined,
        model: chatModel.value,
        tokens_used: 0,
        timestamp: new Date().toISOString(),
      })
    }

    await loadConversations()

  } catch (e: any) {
    if (e.name === 'AbortError') {
      // 用户中断
      if (streamingContent.value) {
        currentMessages.value.push({
          role: 'assistant',
          content: streamingContent.value + '\n\n*(已中断)*',
          thinking: streamingThinking.value,
          toolCalls: streamingToolCalls.value.length > 0 ? [...streamingToolCalls.value] : undefined,
          model: chatModel.value,
          tokens_used: 0,
          timestamp: new Date().toISOString(),
        })
      }
    } else {
      currentMessages.value.push({
        role: 'assistant',
        content: `处理失败: ${e?.message || '未知错误'}`,
        model: '', tokens_used: 0, timestamp: new Date().toISOString(),
      })
    }
  } finally {
    sending.value = false
    streamingActive.value = false
    streamingContent.value = ''
    streamingThinking.value = ''
    streamingToolCalls.value = []
    abortController = null
    await scrollToBottom()
  }
}

function abortRequest() {
  if (abortController) {
    abortController.abort()
    ElMessage.info('已中断请求')
  }
}

function toggleThinking(idx: number) {
  if (expandedThinking.has(idx)) {
    expandedThinking.delete(idx)
  } else {
    expandedThinking.add(idx)
  }
}

async function handleConvAction(command: string) {
  if (!currentConvId.value) { ElMessage.warning('请先选择或创建一个对话'); return }
  switch (command) {
    case 'share': await shareAsImage(); break
    case 'export_md': await exportChat(); break
    case 'delete': await deleteChat(); break
  }
}

async function shareAsImage() {
  try {
    const { default: html2canvas } = await import('html2canvas')
    const el = messagesRef.value
    if (!el) return

    // 查找背景色
    let bgTarget: HTMLElement | null = el
    let bgColor = 'transparent'
    while (bgTarget) {
      const bg = getComputedStyle(bgTarget).backgroundColor
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') { bgColor = bg; break }
      bgTarget = bgTarget.parentElement
    }
    if (bgColor === 'transparent') bgColor = '#ffffff'

    const rgb = bgColor.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
    const isDark = rgb ? (parseInt(rgb[1]) + parseInt(rgb[2]) + parseInt(rgb[3])) / 3 < 128 : false
    const fb = isDark ? 'rgb(45,45,45)' : '#fafafa'
    const fBorder = isDark ? 'rgb(60,60,60)' : '#e8e8e8'
    const fText = isDark ? 'rgb(160,160,160)' : '#999'
    const fStrong = isDark ? 'rgb(180,180,180)' : '#888'
    const fHint = isDark ? 'rgb(120,120,120)' : '#bbb'

    // 找到 flex 父容器和兄弟元素
    let flexParent: HTMLElement | null = el
    while (flexParent && !flexParent.classList.contains('chat-assistant')) {
      flexParent = flexParent.parentElement
    }

    // 保存所有需要修改的元素的原始样式
    type Saved = { el: HTMLElement; style: string }
    const saved: Saved[] = []
    const save = (e: HTMLElement) => saved.push({ el: e, style: e.style.cssText })

    save(el)
    if (flexParent) {
      save(flexParent)
      // 隐藏 toolbar 和 model-bar（不截入分享图）
      for (const child of Array.from(flexParent.children)) {
        if (child !== el) save(child as HTMLElement)
      }
    }

    // 1) 解除 flex 父容器约束
    if (flexParent) {
      flexParent.style.cssText += 'display:block !important;height:auto !important;min-height:0 !important;'
      // 隐藏 toolbar / model-bar
      for (const child of Array.from(flexParent.children)) {
        if (child !== el) {
          (child as HTMLElement).style.cssText += 'display:none !important;'
        }
      }
    }

    // 2) 展开消息容器（左右保留边距，上下取消避免多余留白）
    el.scrollTop = 0
    el.style.cssText += 'flex:none !important;overflow:visible !important;height:auto !important;padding:0 16px !important;'

    // 3) 注入 header（顶部）+ spacer + footer（底部）
    const header = document.createElement('div')
    header.style.cssText = 'display:flex;align-items:center;gap:12px;margin:0 -16px;padding:20px 24px 16px;border-bottom:1px solid rgba(255,255,255,0.1);background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);'
    header.innerHTML = `
      <div style="width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#e94560,#533483);display:flex;align-items:center;justify-content:center;flex-shrink:0;">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
          <polyline points="16 7 22 7 22 13"/>
        </svg>
      </div>
      <div>
        <div style="font-size:16px;font-weight:700;color:#fff;letter-spacing:0.5px;">轮动策略</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.55);margin-top:2px;">A股板块轮动量化分析平台</div>
      </div>`

    const spacer = document.createElement('div')
    spacer.style.height = '16px'

    const footer = document.createElement('div')
    footer.style.cssText = `margin:0 -16px;padding:14px 24px 16px;border-top:1px solid ${fBorder};background:${fb};font-size:11px;color:${fText};line-height:1.6;`
    footer.innerHTML = `
      <div style="color:${fHint};font-size:10px;margin-bottom:4px;">&#9888; 风险提示</div>
      <div>以上内容由 AI 模型生成，仅供参考，<strong style="color:${fStrong};">不构成任何投资建议</strong>。投资有风险，入市需谨慎。历史数据和回测结果不代表未来收益，请结合自身风险承受能力独立判断。</div>`

    el.prepend(header)
    header.after(spacer)
    el.appendChild(footer)

    // 等两帧让浏览器完成布局
    await new Promise(r => requestAnimationFrame(r))
    await new Promise(r => requestAnimationFrame(r))

    // 4) 截取 .chat-messages（含 header + 全部消息 + footer）
    const canvas = await html2canvas(el, {
      scale: 2,
      useCORS: true,
      backgroundColor: bgColor,
    })

    // 5) 清理临时元素
    header.remove()
    spacer.remove()
    footer.remove()

    // 6) 还原所有元素的原始样式
    for (const s of saved) {
      s.el.style.cssText = s.style
    }

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
  } catch { ElMessage.error('生成图片失败') }
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
  } catch { ElMessage.error('导出失败') }
}

async function deleteChat() {
  try {
    await ElMessageBox.confirm('确定删除此对话？', '提示', { type: 'warning' })
    await aiApi.deleteConversation(currentConvId.value)
    ElMessage.success('对话已删除')
    currentConvId.value = ''
    currentMessages.value = []
    sessionStorage.removeItem(STATE_KEY)
    await loadConversations()
  } catch {}
}

function renderMarkdown(text: string): string {
  return md.render(text)
}

function formatToolResult(result: string): string {
  try {
    const obj = JSON.parse(result)
    return JSON.stringify(obj, null, 2)
  } catch {
    return result
  }
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
  display: flex; flex-direction: column; height: 100%; background: var(--bg-primary);

  .chat-toolbar {
    display: flex; align-items: center; gap: 6px;
    padding: 8px 12px; border-bottom: 1px solid var(--border-secondary); background: var(--bg-tertiary);
  }

  .model-bar {
    display: flex; gap: 6px; padding: 6px 12px;
    border-bottom: 1px solid var(--border-secondary);
  }

  .chat-messages {
    flex: 1; overflow-y: auto; padding: 16px;

    .welcome {
      text-align: center; padding: 30px 16px;
      .welcome-icon { font-size: 48px; margin-bottom: 10px; }
      .welcome-text { font-size: 18px; font-weight: 600; margin-bottom: 6px; }
      .welcome-hint { font-size: 13px; color: var(--text-tertiary); margin-bottom: 16px; }
      .quick-questions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }
    }

    .message {
      display: flex; gap: 10px; margin-bottom: 16px;
      &.user {
        flex-direction: row-reverse;
        .avatar { background: var(--accent-primary); color: var(--text-inverse); }
        .content { align-items: flex-end; }
      }
      .avatar {
        flex-shrink: 0; width: 32px; height: 32px; border-radius: 50%;
        background: var(--bg-tertiary); display: flex; align-items: center; justify-content: center; font-size: 14px;
      }
      .content {
        display: flex; flex-direction: column; max-width: 80%;
        .user-text {
          padding: 10px 14px; background: var(--accent-primary-light); border-radius: 12px 12px 2px 12px;
          font-size: 14px; line-height: 1.6; white-space: pre-wrap;
        }
        .md-body {
          padding: 12px 16px; background: var(--bg-tertiary); border-radius: 12px 12px 12px 2px;
          font-size: 14px; line-height: 1.7; word-break: break-word;
          :deep(p) { margin: 0 0 8px 0; &:last-child { margin-bottom: 0; } }
          :deep(h1), :deep(h2), :deep(h3) { margin: 12px 0 6px 0; font-weight: 600; }
          :deep(code) { background: var(--bg-elevated); padding: 1px 4px; border-radius: 3px; font-size: 13px; }
          :deep(pre) { background: #1e1e1e; color: #d4d4d4; padding: 10px 14px; border-radius: 6px; overflow-x: auto; margin: 8px 0; code { background: none; padding: 0; color: inherit; } }
          :deep(table) { border-collapse: collapse; margin: 8px 0; th, td { border: 1px solid var(--border-secondary); padding: 4px 8px; } th { background: var(--bg-tertiary); } }
          :deep(a) { color: var(--accent-primary); }
        }
        .meta { font-size: 11px; color: var(--text-tertiary); margin-top: 4px; }
      }
    }

    .thinking-block {
      margin-bottom: 8px; border: 1px solid var(--border-secondary); border-radius: 8px; overflow: hidden;
      .thinking-header {
        display: flex; align-items: center; gap: 6px;
        padding: 6px 12px; background: var(--bg-tertiary); cursor: pointer;
        font-size: 12px; color: var(--text-tertiary);
        &:hover { background: var(--border-primary); }
      }
      .thinking-content {
        padding: 10px 12px; font-size: 12px; color: var(--text-secondary);
        line-height: 1.6; white-space: pre-wrap; max-height: 200px; overflow-y: auto;
        background: var(--bg-secondary);
      }
      &.expanded .thinking-header { background: var(--border-primary); }
    }

    .tool-call-block {
      margin-bottom: 8px; border: 1px solid var(--accent-primary-light); border-radius: 8px; overflow: hidden;
      .tool-call-header {
        display: flex; align-items: center; gap: 6px;
        padding: 6px 12px; background: var(--accent-primary-light); font-size: 12px; color: var(--accent-primary);
      }
      .tool-call-loading {
        padding: 8px 12px; font-size: 12px; color: var(--text-tertiary); font-style: italic;
      }
      .tool-call-result {
        padding: 8px 12px; background: var(--bg-tertiary);
        pre { margin: 0; font-size: 11px; color: var(--text-secondary); white-space: pre-wrap; word-break: break-all; max-height: 150px; overflow-y: auto; }
      }
    }

    .thinking-spinner { animation: spin 1s linear infinite; }
    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

    .tool-spinner { animation: pulse 1.5s ease-in-out infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

    .typing {
      display: flex; gap: 4px; padding: 12px 16px; background: var(--bg-tertiary); border-radius: 12px;
      span { width: 6px; height: 6px; background: var(--text-tertiary); border-radius: 50%; animation: typing 1.4s infinite;
        &:nth-child(2) { animation-delay: 0.2s; }
        &:nth-child(3) { animation-delay: 0.4s; }
      }
    }
  }

  .quick-actions {
    display: flex; gap: 6px; padding: 8px 12px;
    border-top: 1px solid var(--border-secondary); overflow-x: auto;
    .action-tag { cursor: pointer; white-space: nowrap; &:hover { background: var(--accent-primary-light); } &.disabled { opacity: 0.5; pointer-events: none; } }
  }

  .chat-input {
    padding: 10px 12px; border-top: 1px solid var(--border-secondary);
    display: flex; gap: 8px; align-items: flex-end;
    :deep(.el-textarea__inner) { resize: none; border-radius: 8px; }
    .input-actions { display: flex; align-items: flex-end; }
    .send-btn { height: 56px; border-radius: 8px; }
  }
}

@media (max-width: 480px) {
  .content { max-width: 90% !important; }
  .toolbar { flex-wrap: wrap; gap: 4px; }
}

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-4px); }
}
</style>
