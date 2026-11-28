import request from './request'

export const dataApi = {
  /** A 股真实交易日列表（YYYYMMDD），接口只返回截至今天的最近 N 个交易日 */
  getTradeDates(days = 400): Promise<string[]> {
    return request.get('/data/trade-dates', {
      params: { days },
      headers: { 'X-Silent': true },
    })
  },
}
