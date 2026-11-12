import request from './request'

export type ChartView = 'day' | 'week' | 'month'
export type StepUnit = 'day' | 'week'

export interface KlineBar {
  date: string
  /** 该K线在训练区间内的序号（1-based），划线按此锚定，切换周期视图时据此对齐 */
  no?: number
  open: number
  close: number
  high: number
  low: number
  volume: number
  amount: number
  change_pct: number
  turnover: number
}

export type SenseLineType = 'hline' | 'trend' | 'channel' | 'rect' | 'fib'

export interface SenseLinePoint {
  /** 训练区间内的K线序号 */
  x: number
  price: number
}

export interface SenseLine {
  type: SenseLineType
  points: SenseLinePoint[]
  color: string
}

export interface SensePair {
  buy_date: string
  buy_price: number
  sell_date: string
  sell_price: number
  shares: number
  pnl: number
  pnl_pct: number
  days: number
  forced?: boolean
}

export interface SenseChart {
  bars: KlineBar[]
  ma: Record<string, (number | null)[]>
  macd: { dif: number[]; dea: number[]; macd: number[] }
  vol_ma: Record<string, (number | null)[]>
  /** 后市第一根在 bars 中的下标；等于 bars.length 表示没有后市 */
  future_start?: number
  /** 训练区间之后追加的真实行情根数 */
  future_bars?: number
}

export interface SensePosition {
  shares: number
  cost_price: number
  cost_amount: number
  buy_date: string
  buy_index: number
}

export interface SenseTrade {
  action: 'BUY' | 'SELL'
  date: string
  /** 训练区间内第几根K线（1-based），图表按此锚定买卖点，旧记录可能缺失 */
  no?: number
  price: number
  shares: number
  amount: number
  fee: number
  /** 本次交易所用仓位比例 */
  ratio?: number
  forced?: boolean
  /** 卖出时的 FIFO 配对明细 */
  matches?: SensePair[]
}

export interface SenseState {
  session_id: string
  ended: boolean
  current_date: string
  start_date: string
  progress: { current: number; total: number }
  cash: number
  market_value: number
  equity: number
  return_pct: number
  float_pnl_pct: number | null
  position: SensePosition | null
  trades: SenseTrade[]
  /** 训练中保存的划线（后端会话持久化） */
  lines?: SenseLine[]
  can_buy: boolean
  can_sell: boolean
  can_step: boolean
}

/** K线形态标准示意图 */
export interface SensePatternShape {
  name: string
  focus: number
  /** [open, high, low, close]，价格归一化到 0~100 */
  bars: [number, number, number, number][]
  note: string
  /** 本系统实际命中条件（含量能/均线等图中画不出的部分） */
  rule?: string
}

/** 盘后总结的一条理由 */
export interface SenseReviewReason {
  tag: string
  text: string
  title: string
  /** 统计方向：1 偏多 / -1 偏空 / 0 中性（两半样本方向不一致） */
  bias: number
  weight: number
  /** 实测方向与教科书方向相反 */
  contrarian: boolean
  /** 标准形态示意图 key */
  pattern?: string
  /** 离线校准统计（旧结构可能缺失） */
  stat?: {
    n: number
    r5: number
    pos5: number
    h0: number
    h1: number
    side: number
  }
}

/** 参考点时点的真实局部K线（只含触发根及之前，不含未来数据） */
export interface SenseReviewWindowBar {
  d: string
  o: number
  h: number
  l: number
  c: number
  v: number
}

/** 盘后总结的买卖参考点 */
export interface SenseReviewSignal {
  /** 训练区间内第几根K线 */
  no: number
  date: string
  price: number
  score: number
  net?: number
  confidence?: string
  action: 'buy' | 'sell' | 'watch'
  title: string
  execute?: string
  horizon?: number
  invalidate?: number
  focus?: number
  window?: SenseReviewWindowBar[]
  reasons: SenseReviewReason[]
}

export interface SenseReview {
  range: {
    start: string
    end: string
    bars: number
    change_pct?: number
    max_drawdown?: number
  }
  summary: string
  /** 统计口径与不确定性说明 */
  method?: string
  /** 形态名 → 标准示意图 */
  patterns?: Record<string, SensePatternShape>
  signals: SenseReviewSignal[]
  counts: Record<string, number>
}

/** 训练区间之后的真实行情摘要 */
export interface SenseFuture {
  bars: number
  start_date: string
  end_date: string
  dates: string[]
  closes: number[]
  change_pct: number
}

export interface SenseSummary {
  session_id: string
  user: string
  code: string
  name: string
  start_date: string
  end_date: string
  /** 原定训练区间末尾（复盘时可看到结束后的行情），旧记录可能缺失 */
  window_end?: string
  initial_capital: number
  final_equity: number
  return_pct: number
  benchmark_pct: number
  excess_pct: number
  trade_count: number
  hold_days: number
  forced_exit: boolean
  trades: SenseTrade[]
  /** FIFO 买卖配对明细（旧记录没有该字段） */
  pairs?: SensePair[]
  /** 训练中画的线（旧记录没有该字段） */
  lines?: SenseLine[]
  /** 盘后总结（旧记录复盘时现场回算） */
  review?: SenseReview
  /** 后续走势摘要（仅结算响应带，旧记录没有） */
  future?: SenseFuture
  created_at: string
}

export interface SenseStats {
  total: number
  win_count: number
  win_rate: number | null
  avg_return: number | null
  avg_excess: number | null
  best_return: number | null
  worst_return: number | null
  cumulative_return: number | null
  avg_hold_days: number | null
  avg_trade_count: number | null
  records: SenseSummary[]
}

export interface StartResult {
  session: SenseState
  chart: SenseChart
}

export interface StepResult {
  session: SenseState
  chart: SenseChart
  summary: SenseSummary | null
}

export interface SenseReplay {
  record: SenseSummary
  chart: SenseChart
}

export const stockSenseApi = {
  /** 开始新一轮训练（随机标的 + 随机一年区间） */
  start(user: string): Promise<StartResult> {
    return request.post('/strategy/stock-sense/start', null, { params: { user } })
  },

  /** 当前可见K线（切换视图时调用，不推进） */
  chart(sid: string, view: ChartView): Promise<{ chart: SenseChart; session: SenseState }> {
    return request.get(`/strategy/stock-sense/${sid}/chart`, { params: { view } })
  },

  /** 推进下一根K线 */
  step(sid: string, unit: StepUnit, view: ChartView): Promise<StepResult> {
    return request.post(`/strategy/stock-sense/${sid}/step`, null, { params: { unit, view } })
  },

  /** 按仓位比例买入 / 卖出（ratio=1 为满仓买入或清仓卖出） */
  trade(
    sid: string,
    action: 'buy' | 'sell',
    ratio: number,
    view: ChartView,
  ): Promise<{ session: SenseState; chart: SenseChart }> {
    return request.post(`/strategy/stock-sense/${sid}/trade`, null, {
      params: { action, ratio, view },
    })
  },

  /** 保存训练中的划线（整体覆盖） */
  saveLines(sid: string, lines: SenseLine[]): Promise<{ lines: SenseLine[] }> {
    return request.post(`/strategy/stock-sense/${sid}/lines`, { lines })
  },

  /** 主动结束训练并结算（返回还原真实日期后的图表，与 session 口径一致） */
  finish(
    sid: string,
    view: ChartView,
  ): Promise<{ summary: SenseSummary; session: SenseState; chart: SenseChart }> {
    return request.post(`/strategy/stock-sense/${sid}/finish`, null, { params: { view } })
  },

  /** 训练统计（含历史记录） */
  stats(user: string): Promise<SenseStats> {
    return request.get(`/strategy/stock-sense/stats/${encodeURIComponent(user)}`)
  },

  /** 复盘：按历史记录回放训练区间的K线与买卖点 */
  replay(sessionId: string, user: string, view: ChartView): Promise<SenseReplay> {
    return request.get(`/strategy/stock-sense/replay/${encodeURIComponent(sessionId)}`, {
      params: { user, view },
    })
  },
}
