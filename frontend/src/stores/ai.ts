import { defineStore } from 'pinia'
import { ref } from 'vue'
import { aiApi } from '@/api/ai'
import type { ProviderConfig } from '@/api/ai'

// AI 对话页的会话状态键（sessionStorage），换账号时必须清掉
export const AI_CHAT_STATE_KEY = 'ai_chat_state'

const DEFAULT_PROVIDER = 'deepseek'
const DEFAULT_MODEL = 'deepseek-chat'

export const useAiStore = defineStore('ai', () => {
  const providers = ref<ProviderConfig[]>([])
  const lastProvider = ref(localStorage.getItem('ai_chat_provider') || DEFAULT_PROVIDER)
  const lastModel = ref(localStorage.getItem('ai_chat_model') || DEFAULT_MODEL)

  async function loadProviders() {
    try {
      providers.value = await aiApi.listProviders(true)
    } catch {
      providers.value = []
    }
  }

  function setProvider(provider: string, model: string) {
    lastProvider.value = provider
    lastModel.value = model
    localStorage.setItem('ai_chat_provider', provider)
    localStorage.setItem('ai_chat_model', model)
  }

  // 换账号时调用：提供商列表、模型偏好、对话状态都属于上一个账号，不能留给下一个
  function reset() {
    providers.value = []
    lastProvider.value = DEFAULT_PROVIDER
    lastModel.value = DEFAULT_MODEL
    localStorage.removeItem('ai_chat_provider')
    localStorage.removeItem('ai_chat_model')
    sessionStorage.removeItem(AI_CHAT_STATE_KEY)
  }

  return { providers, lastProvider, lastModel, loadProviders, setProvider, reset }
})
