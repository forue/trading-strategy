import { defineStore } from 'pinia'
import { ref } from 'vue'
import { aiApi } from '@/api/ai'
import type { ProviderConfig } from '@/api/ai'

export const useAiStore = defineStore('ai', () => {
  const providers = ref<ProviderConfig[]>([])
  const lastProvider = ref(localStorage.getItem('ai_chat_provider') || 'deepseek')
  const lastModel = ref(localStorage.getItem('ai_chat_model') || 'deepseek-chat')

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

  return { providers, lastProvider, lastModel, loadProviders, setProvider }
})
