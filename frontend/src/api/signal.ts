import request from './request'

export interface TradeSignal {
  id: number
  signal_date: string
  strategy_type: 'AGGRESSIVE' | 'MODERATE' | 'CONSERVATIVE'
  sector_code: string
  sector_name: string
  etf_code: string | null
  etf_name: string | null
  direction: 'BUY' | 'SELL'
  position_ratio: number
  score: number
  reason: string
  rank: number | null
  total_sectors: number | null
  created_at: string | null
}

export const signalApi = {
  getTodaySignals(strategyType: string): Promise<TradeSignal[]> {
    return request.get('/signals/today', { params: { strategy_type: strategyType } })
  },

  getSignalHistory(params: { strategyType: string; startDate: string; endDate: string }): Promise<TradeSignal[]> {
    return request.get('/signals/history', {
      params: {
        strategy_type: params.strategyType,
        start_date: params.startDate,
        end_date: params.endDate,
      }
    })
  },

  getSignalCalendar(params: { strategyType: string; month: string }): Promise<TradeSignal[]> {
    return request.get('/signals/calendar', {
      params: {
        strategy_type: params.strategyType,
        month: params.month,
      }
    })
  },
}
