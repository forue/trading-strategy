import request from './request'

export type WorkshopScenario = 'AGGRESSIVE' | 'MODERATE' | 'CONSERVATIVE'
export type WorkshopStatus = 'draft' | 'active' | 'paused'

export interface WorkshopCondition {
  field: string
  op: string
  value: any
}

export interface WorkshopAction {
  type: string
  value: any
}

export interface WorkshopPayload {
  name: string
  scenario: WorkshopScenario
  description: string
  condition_logic: 'AND' | 'OR'
  conditions: WorkshopCondition[]
  actions: WorkshopAction[]
  risk: Record<string, number>
  is_public: boolean
  status: WorkshopStatus
}

export interface WorkshopStrategy extends WorkshopPayload {
  id: number
  user_id: number
  version: number
  owner_name?: string
  is_owner?: boolean
  like_count?: number
  liked_by_me?: boolean
  run_count?: number
  version_count?: number
  created_at: string
  updated_at: string
}

export interface WorkshopVersion {
  version: number
  change_note: string
  created_at: string
  snapshot: WorkshopPayload
}

export interface WorkshopAlgorithm {
  id: number | string
  user_id?: number
  name: string
  description: string
  conditions: WorkshopCondition[]
  created_at?: string
  updated_at?: string
}

export interface WorkshopRun {
  id: number
  strategy_id: number
  mode: 'simulation' | 'live'
  status: 'success' | 'failed'
  result: Record<string, any> | null
  error: string | null
  started_at: string
  finished_at: string
}

// request 的响应拦截器已拆出 data，这里用 async 签名标注业务类型即可
export const workshopApi = {
  list: async (scope: 'mine' | 'public' = 'mine'): Promise<WorkshopStrategy[]> =>
    request.get('/strategy/workshop/strategies', { params: { scope } }),
  get: async (id: number): Promise<WorkshopStrategy> => request.get(`/strategy/workshop/strategies/${id}`),
  create: async (payload: WorkshopPayload): Promise<WorkshopStrategy> =>
    request.post('/strategy/workshop/strategies', payload),
  update: async (id: number, payload: WorkshopPayload, changeNote = ''): Promise<WorkshopStrategy> =>
    request.put(`/strategy/workshop/strategies/${id}`, payload, { params: { change_note: changeNote } }),
  remove: (id: number) => request.delete(`/strategy/workshop/strategies/${id}`),
  versions: async (id: number): Promise<WorkshopVersion[]> =>
    request.get(`/strategy/workshop/strategies/${id}/versions`),
  fork: async (id: number): Promise<WorkshopStrategy> =>
    request.post(`/strategy/workshop/strategies/${id}/fork`),
  apply: async (id: number, body: { mode: 'simulation' | 'live'; start_date?: string; end_date?: string; initial_capital?: number }): Promise<{ run: WorkshopRun; result: Record<string, any> }> =>
    request.post(`/strategy/workshop/strategies/${id}/apply`, body, { timeout: 300000 }),
  listRuns: async (strategyId?: number): Promise<WorkshopRun[]> =>
    request.get('/strategy/workshop/runs', { params: { strategy_id: strategyId } }),
  getRun: async (id: number): Promise<WorkshopRun> => request.get(`/strategy/workshop/runs/${id}`),
  like: async (id: number): Promise<{ like_count: number; liked_by_me: boolean }> =>
    request.post(`/strategy/workshop/strategies/${id}/like`),
  unlike: async (id: number): Promise<{ like_count: number; liked_by_me: boolean }> =>
    request.delete(`/strategy/workshop/strategies/${id}/like`),
  builtinAlgorithms: async (): Promise<WorkshopAlgorithm[]> =>
    request.get('/strategy/workshop/algorithms/builtin'),
  listAlgorithms: async (): Promise<WorkshopAlgorithm[]> =>
    request.get('/strategy/workshop/algorithms'),
  createAlgorithm: async (payload: Omit<WorkshopAlgorithm, 'id'>): Promise<WorkshopAlgorithm> =>
    request.post('/strategy/workshop/algorithms', payload),
  updateAlgorithm: async (id: number, payload: Omit<WorkshopAlgorithm, 'id'>): Promise<WorkshopAlgorithm> =>
    request.put(`/strategy/workshop/algorithms/${id}`, payload),
  deleteAlgorithm: (id: number) => request.delete(`/strategy/workshop/algorithms/${id}`),
}
