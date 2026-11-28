import dayjs from 'dayjs'
import { ref } from 'vue'
import { dataApi } from '@/api/data'

const tradeDates = ref<Set<string>>(new Set())
const range = ref<[string, string] | null>(null)
let loaded = false
let pending: Promise<void> | null = null

/** 真实 A 股交易日历：接口数据 + 周末兜底，全局只拉一次 */
export function useTradeCalendar() {
  async function ensureTradeDates() {
    if (loaded) return
    if (pending) return pending
    pending = dataApi.getTradeDates(400)
      .then((days) => {
        const dates = (days || []).map((d) => String(d).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')).sort()
        tradeDates.value = new Set(dates)
        range.value = dates.length ? [dates[0], dates[dates.length - 1]] : null
        loaded = dates.length > 0
      })
      .catch(() => { loaded = false })
      .finally(() => { pending = null })
    return pending
  }

  function isTradeDay(date: string) {
    if ([0, 6].includes(dayjs(date).day())) return false
    // 接口只给最近 N 个交易日：范围外的数据不可信，只按周末兜底，避免误标休市
    if (!range.value || date < range.value[0] || date > range.value[1]) return true
    return tradeDates.value.has(date)
  }

  return { ensureTradeDates, isTradeDay }
}
