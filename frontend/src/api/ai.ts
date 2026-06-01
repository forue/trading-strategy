import request from './request'

export interface SignalAnalysis {
  sector_code: string
  sector_name: string
  direction: string
  interpretation: string
  risk_factors: string[]
  confidence: number
  suggestion: string
  model: string
  tokens_used: number
  latency_ms: number
}

export interface RiskAlert {
  alert_type: string
  level: 'INFO' | 'WARNING' | 'CRITICAL'
  title: string
  description: string
  suggestion: string
  metrics: Record<string, any>
}

export interface AiConfig {
  provider: string
  api_key: string
  base_url: string
  model: string
  temperature: number
  max_tokens: number
  ollama_base_url: string
  ollama_model: string
  has_api_key: boolean
  signal_analysis_provider?: string
  signal_analysis_model?: string
}

export interface DailyReviewReport {
  date: string
  market_summary: string
  sector_rotation: string
  portfolio_review: string
  tomorrow_outlook: string
  model: string
  tokens_used: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  model: string
  tokens_used: number
  timestamp: string
}

export interface ModelInfo {
  value: string
  label: string
  desc: string
}

export interface ProviderConfig {
  id: string
  name: string
  base_url: string
  api_key: string
  models: ModelInfo[]
  is_builtin: boolean
  is_configured: boolean
}

export interface Conversation {
  id: string
  title: string
  provider: string
  model: string
  messages: ChatMessage[]
  created_at: string
  updated_at: string
  message_count: number
}

export const aiApi = {
  analyzeSignal(strategyType: string, signalDate?: string): Promise<{ analyses: SignalAnalysis[] }> {
    return request.post('/ai/analyze-signal', {
      strategy_type: strategyType,
      signal_date: signalDate,
    }, { headers: { 'X-Silent': '1' } })
  },

  riskCheck(strategyType?: string): Promise<{ alerts: RiskAlert[]; overall_risk: string }> {
    return request.post('/ai/risk-check', {
      strategy_type: strategyType || 'MODERATE',
    }, { headers: { 'X-Silent': '1' } })
  },

  getAnalysisHistory(strategyType: string, startDate: string, endDate: string): Promise<{ history: any[]; count: number }> {
    return request.get('/ai/analysis-history', {
      params: { strategy_type: strategyType, start_date: startDate, end_date: endDate },
    }, { headers: { 'X-Silent': '1' } })
  },

  getConfig(): Promise<AiConfig> {
    return request.get('/ai/config')
  },

  updateConfig(config: Partial<AiConfig>): Promise<AiConfig> {
    return request.put('/ai/config', config)
  },

  chat(message: string, conversationId?: string, provider?: string, model?: string, noSave?: boolean): Promise<{
    conversation_id: string
    reply: string
    model: string
    tokens_used: number
  }> {
    return request.post('/ai/chat', {
      message,
      conversation_id: conversationId || '',
      provider: provider || '',
      model: model || '',
      no_save: noSave || false,
    }, { timeout: 300000 })
  },

  dailyReview(date?: string): Promise<DailyReviewReport> {
    return request.post('/ai/daily-review', {
      date: date || '',
    })
  },

  listOllamaModels(baseUrl?: string): Promise<{ name: string; size: number }[]> {
    const params: any = {}
    if (baseUrl) params.base_url = baseUrl
    return request.get('/ai/models', { params }).then((res: any) => res.models || [])
  },

  // 提供商管理
  listProviders(configuredOnly?: boolean): Promise<ProviderConfig[]> {
    const params: any = {}
    if (configuredOnly) params.configured_only = true
    return request.get('/ai/providers', { params })
  },

  getProvider(providerId: string): Promise<ProviderConfig> {
    return request.get(`/ai/providers/${providerId}`)
  },

  saveProvider(provider: Partial<ProviderConfig>): Promise<ProviderConfig> {
    return request.post('/ai/providers', provider)
  },

  deleteProvider(providerId: string): Promise<void> {
    return request.delete(`/ai/providers/${providerId}`)
  },

  testProvider(providerId: string): Promise<{ connected: boolean; error?: string }> {
    return request.post(`/ai/providers/${providerId}/test`, {}, { timeout: 30000 })
  },

  // 对话管理
  listConversations(): Promise<Conversation[]> {
    return request.get('/ai/conversations')
  },

  getConversation(convId: string): Promise<Conversation> {
    return request.get(`/ai/conversations/${convId}`)
  },

  deleteConversation(convId: string): Promise<void> {
    return request.delete(`/ai/conversations/${convId}`)
  },

  exportConversation(convId: string, fmt: string = 'markdown'): Promise<string> {
    return request.get(`/ai/conversations/${convId}/export`, {
      params: { fmt },
      responseType: 'text',
    } as any)
  },
}
