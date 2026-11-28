<template>
  <div class="fund-page">
    <el-row :gutter="20" class="summary-row">
      <el-col :xs="12" :sm="12" :md="4" :lg="4" v-for="item in summaryItems" :key="item.label">
        <div class="summary-card">
          <div class="summary-label">{{ item.label }}</div>
          <div class="summary-value" :style="{ color: themeColors[item.colorKey] }">{{ item.value }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="chart-row">
      <el-col :xs="24" :md="16">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">净值 / 累计收益率曲线</span>
            <el-form :inline="true" size="small">
              <el-form-item>
                <el-select v-model="curveMonths" style="width: 90px" @change="loadProfitCurve">
                  <el-option label="1月" value="1" />
                  <el-option label="3月" value="3" />
                  <el-option label="6月" value="6" />
                  <el-option label="1年" value="12" />
                </el-select>
              </el-form-item>
            </el-form>
          </div>
          <v-chart :option="navChartOption" class="fill-chart nav-chart" autoresize />
          <el-row :gutter="12" class="stats-row">
            <el-col :xs="12" :sm="6" v-for="s in profitStats" :key="s.label">
              <div class="stat-item">
                <span class="stat-label">{{ s.label }}</span>
                <span class="stat-val" :style="{ color: s.color }">{{ s.value }}</span>
              </div>
            </el-col>
          </el-row>
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">月度收益率</span>
          </div>
          <v-chart :option="monthlyBarOption" class="fill-chart" autoresize />
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="chart-row page-section">
      <el-col :xs="24" :md="16">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">每日盈亏日历</span>
            <el-date-picker v-model="calendarMonth" type="month" placeholder="选择月份" size="small" value-format="YYYY-MM" @change="loadDailyPnl" />
          </div>
          <v-chart :option="pnlCalendarOption" class="fill-chart calendar-chart" autoresize />
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">收益归因分析</span>
          </div>
          <v-chart :option="attributionChartOption" class="fill-chart" autoresize />
        </div>
      </el-col>
    </el-row>

    <div class="page-card page-section">
      <div class="card-header">
        <span class="card-title">银证转账</span>
        <el-button type="primary" size="small" @click="showTransferDialog = true">
          <el-icon><Plus /></el-icon> 新增转账
        </el-button>
      </div>
      <!-- 手机端：转账记录改为「日期+金额」双行条目 -->
      <ul v-if="isMobile" class="m-list">
        <li v-for="row in transfers" :key="row.id" class="m-list-row">
          <div class="m-row-main">
            <span class="m-row-date">{{ row.transfer_date }}</span>
            <span class="m-row-amount" :style="{ color: row.direction === 'DEPOSIT' ? themeColors.loss : themeColors.profit }">
              {{ row.direction === 'DEPOSIT' ? '+' : '-' }}¥{{ row.amount.toLocaleString() }}
            </span>
          </div>
          <div class="m-row-sub">
            <el-tag :type="row.direction === 'DEPOSIT' ? 'success' : 'danger'" size="small">
              {{ row.direction === 'DEPOSIT' ? '入金' : '出金' }}
            </el-tag>
            <span class="m-row-remark">{{ row.remark || '—' }}</span>
            <el-button type="danger" size="small" link @click="deleteTransfer(row.id)">删除</el-button>
          </div>
        </li>
        <li v-if="transfers.length === 0" class="m-list-empty">暂无转账记录</li>
      </ul>

      <div v-else class="responsive-table"><el-table :data="transfers" stripe empty-text="暂无转账记录">
        <el-table-column prop="transfer_date" label="日期" width="110" />
        <el-table-column label="方向" width="80">
          <template #default="{ row }">
            <el-tag :type="row.direction === 'DEPOSIT' ? 'success' : 'danger'" size="small">
              {{ row.direction === 'DEPOSIT' ? '入金' : '出金' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="140" align="right">
          <template #default="{ row }">
            <span :style="{ color: row.direction === 'DEPOSIT' ? themeColors.loss : themeColors.profit }">
              {{ row.direction === 'DEPOSIT' ? '+' : '-' }}¥{{ row.amount.toLocaleString() }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button type="danger" size="small" link @click="deleteTransfer(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table></div>
    </div>

    <div class="page-card page-section">
      <div class="card-header">
        <span class="card-title">当前持仓</span>
        <el-select v-model="positionStrategy" size="small" style="width: 120px" @change="loadPositions">
          <el-option label="全部" value="" />
          <el-option label="激进" value="AGGRESSIVE" />
          <el-option label="稳健" value="MODERATE" />
          <el-option label="保守" value="CONSERVATIVE" />
        </el-select>
      </div>
      <!-- 手机端：持仓改为「标题 + 2×2 指标块 + 页脚」卡片 -->
      <ul v-if="isMobile" class="m-pos-list">
        <li v-for="(row, i) in positions" :key="i" class="m-pos-card">
          <div class="m-pos-head">
            <span class="m-pos-sector">{{ row.sector_name }}</span>
            <el-tag size="small">{{ STRATEGY_LABELS[row.strategy_type] ?? row.strategy_type }}</el-tag>
            <span :class="row.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">{{ row.direction === 'BUY' ? '多' : '空' }}</span>
            <span v-if="row.current_price && row.avg_price" class="m-pos-pnl"
              :style="{ color: row.current_price > row.avg_price ? themeColors.profit : themeColors.loss }">
              {{ ((row.current_price - row.avg_price) / row.avg_price * 100).toFixed(2) }}%
            </span>
            <span v-else class="m-pos-pnl text-muted">--</span>
          </div>
          <div class="m-pos-grid">
            <div><em>数量</em><b>{{ row.quantity }}</b></div>
            <div><em>均价</em><b>¥{{ row.avg_price?.toFixed(4) }}</b></div>
            <div><em>现价</em><b>¥{{ row.current_price?.toFixed(4) }}</b></div>
            <div><em>仓位</em><b>{{ (row.position_ratio * 100).toFixed(1) }}%</b></div>
          </div>
          <div class="m-pos-foot">
            盈亏 {{ row.current_price && row.avg_price ? '¥' + ((row.current_price - row.avg_price) * row.quantity).toFixed(2) : '--' }}
            · 开仓 {{ (row.opened_at || '').slice(0, 16) || '--' }}
          </div>
        </li>
        <li v-if="positions.length === 0" class="m-list-empty">暂无持仓</li>
      </ul>

      <div v-else class="responsive-table"><el-table :data="positions" stripe empty-text="暂无持仓">
        <el-table-column prop="sector_name" label="板块" width="96" />
        <el-table-column prop="strategy_type" label="策略" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ STRATEGY_LABELS[row.strategy_type] ?? row.strategy_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="direction" label="方向" width="64">
          <template #default="{ row }">
            <span :class="row.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">{{ row.direction === 'BUY' ? '多' : '空' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" width="96" align="right" />
        <el-table-column prop="avg_price" label="均价" width="96" align="right">
          <template #default="{ row }">¥{{ row.avg_price?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column prop="current_price" label="现价" width="96" align="right">
          <template #default="{ row }">¥{{ row.current_price?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column label="盈亏" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.current_price && row.avg_price" :style="{ color: row.current_price > row.avg_price ? themeColors.profit : themeColors.loss }">
              {{ ((row.current_price - row.avg_price) / row.avg_price * 100).toFixed(2) }}%
              (¥{{ ((row.current_price - row.avg_price) * row.quantity).toFixed(2) }})
            </span>
            <span v-else class="text-muted">--</span>
          </template>
        </el-table-column>
        <el-table-column prop="position_ratio" label="仓位" width="80" align="right">
          <template #default="{ row }">{{ (row.position_ratio * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column prop="opened_at" label="开仓时间" min-width="140" />
      </el-table></div>
    </div>

    <el-dialog v-model="showTransferDialog" title="新增银证转账" width="460px">
      <el-form :model="transferForm" label-width="70px">
        <el-form-item label="日期">
          <el-date-picker v-model="transferForm.date" type="date" placeholder="选择日期" value-format="YYYY-MM-DD"
            style="width: 100%" />
        </el-form-item>
        <el-form-item label="方向">
          <el-radio-group v-model="transferForm.direction">
            <el-radio value="DEPOSIT">入金（银行→证券）</el-radio>
            <el-radio value="WITHDRAW">出金（证券→银行）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="金额">
          <el-input-number v-model="transferForm.amount" :min="0" :step="10000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="transferForm.remark" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTransferDialog = false">取消</el-button>
        <el-button type="primary" @click="submitTransfer">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart, PieChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, CalendarComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fundApi } from '@/api/fund'
import { useThemeStore } from '@/stores/theme'
import type { Position, NavRecord, DailyPnl, BankTransfer, ProfitCurveData } from '@/api/fund'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { useTradeCalendar } from '@/composables/useTradeCalendar'
import { calendarItemStyle, calendarLabelBase, calendarSurfaceColor, calendarCellPalette, calendarEmphasisItemStyle } from '@/utils/calendarStyle'

const { isMobile, isTablet } = useBreakpoint()
const { ensureTradeDates, isTradeDay } = useTradeCalendar()

use([LineChart, BarChart, PieChart, HeatmapChart, CalendarComponent, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, CanvasRenderer])

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.mode === 'dark')

// 语义色随主题切换：暗色下需提高明度、改用暗色网格/边框，
// 否则深色文字（#303133）与浅灰边框（#dcdee0）在 --bg-secondary(#1a1d24) 上不可读或刺眼。
const themeColors = computed(() => (isDark.value ? {
  profit: '#ff6f61', loss: '#57a182', text: '#e8eaef', textSub: '#9da1b0',
  primary: '#7b93f5', warning: '#e6a23c', grid: '#2a2d38', axis: '#2a2d38',
  tooltipBg: '#252832', tooltipBorder: '#2a2d38',
} : {
  /* 这组色用于 ECharts 与内联数字，不能写 CSS 变量；原 EP 默认
     (#67c23a / #f56c6c / #e6a23c / #409eff) 在白底只有 2.0~3.1:1，统一换成语义色 */
  profit: '#d92d20', loss: '#12805c', text: '#18181b', textSub: '#52525b',
  primary: '#4051E0', warning: '#b54708', grid: '#ebeef5', axis: '#e4e7ed',
  tooltipBg: '#ffffff', tooltipBorder: '#e4e4e1',
}))

// 策略类型中文名：集中定义为 Record，修复模板中用 any 索引对象字面量导致的 TS7053
const STRATEGY_LABELS: Record<string, string> = {
  AGGRESSIVE: '激进',
  MODERATE: '稳健',
  CONSERVATIVE: '保守',
}

const curveMonths = ref('3')
const calendarMonth = ref(dayjs().format('YYYY-MM'))
const positionStrategy = ref('')
const showTransferDialog = ref(false)

const positions = ref<Position[]>([])
const navData = ref<NavRecord[]>([])
const dailyPnlData = ref<DailyPnl[]>([])
const transfers = ref<BankTransfer[]>([])
const attributionData = ref<any[]>([])
const profitCurveData = ref<ProfitCurveData | null>(null)

const transferForm = reactive({
  date: dayjs().format('YYYY-MM-DD'),
  direction: 'DEPOSIT',
  amount: 100000,
  remark: '',
})

type ColorKey = 'text' | 'primary' | 'warning' | 'profit' | 'loss'
const summaryItems = ref<{ label: string; value: string; colorKey: ColorKey }[]>([
  { label: '总资产', value: '--', colorKey: 'text' },
  { label: '可用资金', value: '--', colorKey: 'primary' },
  { label: '持仓市值', value: '--', colorKey: 'warning' },
  { label: '今日盈亏', value: '--', colorKey: 'profit' },
  { label: '累计收益率', value: '--', colorKey: 'loss' },
])

const profitStats = computed(() => {
  const s = profitCurveData.value?.stats
  if (!s) return []
  return [
    { label: '累计收益', value: `${s.total_return_pct}%`, color: s.total_return_pct >= 0 ? themeColors.value.profit : themeColors.value.loss },
    { label: '最大回撤', value: `${s.max_drawdown_pct}%`, color: themeColors.value.warning },
    { label: '年化收益', value: `${s.annual_return_pct}%`, color: s.annual_return_pct >= 0 ? themeColors.value.profit : themeColors.value.loss },
    { label: '夏普比率', value: `${s.sharpe_ratio}`, color: themeColors.value.primary },
  ]
})

const navChartOption = computed(() => {
  if (navData.value.length === 0) return {}
  const c = themeColors.value
  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: c.text },
    },
    legend: {
      data: ['账户净值', '累计收益率'],
      selected: { '账户净值': true, '累计收益率': true },
      textStyle: { color: c.textSub },
    },
    grid: { top: 40, bottom: 20 },
    xAxis: {
      type: 'category', data: navData.value.map(d => d.nav_date), boundaryGap: false,
      axisLabel: { color: c.textSub }, axisLine: { lineStyle: { color: c.axis } },
    },
    yAxis: [
      { type: 'value', name: '净值', scale: true, nameTextStyle: { color: c.textSub }, axisLabel: { color: c.textSub }, axisLine: { lineStyle: { color: c.axis } }, splitLine: { lineStyle: { type: 'dashed', color: c.grid } } },
      { type: 'value', name: '收益率 %', scale: true, nameTextStyle: { color: c.textSub }, axisLabel: { formatter: '{value}%', color: c.textSub }, axisLine: { lineStyle: { color: c.axis } }, splitLine: { show: false } },
    ],
    series: [
      { name: '账户净值', type: 'line', data: navData.value.map(d => d.total_assets), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: c.primary }, areaStyle: { color: isDark.value ? 'rgba(123,147,245,0.12)' : 'rgba(64,158,255,0.08)' } },
      { name: '累计收益率', type: 'line', yAxisIndex: 1, data: navData.value.map(d => (d.cumulative_return * 100).toFixed(2)), smooth: true, lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: c.loss } },
    ],
  }
})

const monthlyBarOption = computed(() => {
  const monthly = profitCurveData.value?.monthly_returns || []
  const c = themeColors.value
  const colors = monthly.map(m => m.return_pct >= 0 ? c.profit : c.loss)
  return {
    tooltip: {
      trigger: 'axis', formatter: (p: any) => `${p[0].name}: ${p[0].value}%`,
      backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: c.text },
    },
    grid: { top: 10, bottom: 30, left: 50, right: 20 },
    xAxis: {
      type: 'category', data: monthly.map(m => m.month.slice(5)),
      axisLabel: { color: c.textSub }, axisLine: { lineStyle: { color: c.axis } },
    },
    yAxis: {
      type: 'value', axisLabel: { formatter: '{value}%', color: c.textSub },
      axisLine: { lineStyle: { color: c.axis } }, splitLine: { lineStyle: { color: c.grid } },
    },
    series: [{
      type: 'bar',
      data: monthly.map((m, i) => ({ value: m.return_pct, itemStyle: { color: colors[i] } })),
      barWidth: '60%',
      label: { show: true, position: 'top', formatter: (p: any) => `${p.value}%`, fontSize: 10, color: c.textSub },
    }],
  }
})

const pnlCalendarOption = computed(() => {
  // 固定 6 周（42 格）网格，周日为一周起点：7 列 × 6 行，不再出现列数抖动
  const firstOfMonth = dayjs(calendarMonth.value + '-01')
  const rangeStart = firstOfMonth.subtract(firstOfMonth.day(), 'day')
  const rangeEnd = rangeStart.add(41, 'day')
  const range: [string, string] = [rangeStart.format('YYYY-MM-DD'), rangeEnd.format('YYYY-MM-DD')]
  const monthPrefix = calendarMonth.value
  const retMap = new Map(dailyPnlData.value.map(d => [d.date, d.daily_return]))

  // 红涨绿跌直接取页面主题语义色，格子与下方色阶条用同一套，不再各写一套硬编码值
  const profitColor = themeColors.value.profit
  const lossColor = themeColors.value.loss
  // 底色由深到浅：本月交易日有收益(红/绿) > 本月交易日无数据 > 本月休市 > 非本月
  // 三档底色与文字色走共用 palette，和信号日历保持同一套观感
  const palette = calendarCellPalette(isDark.value)
  const emphasisStyle = calendarEmphasisItemStyle(isDark.value)
  const { neutral: neutralColor, closed: closedColor, outside: outsideColor } = palette
  const cellStyle = calendarItemStyle(isDark.value, isMobile.value)
  const labelColor = palette.axisText

  const pnlData: any[] = []
  const neutralDates: string[] = []
  const closedDates: string[] = []
  const outsideDates: string[] = []
  for (let i = 0; i < 42; i++) {
    const date = rangeStart.add(i, 'day').format('YYYY-MM-DD')
    if (!date.startsWith(monthPrefix)) { outsideDates.push(date); continue }
    // 休市日不参与收益着色，单独一层浅色，与交易日拉开深浅
    if (!isTradeDay(date)) { closedDates.push(date); continue }
    if (retMap.has(date)) pnlData.push([date, retMap.get(date)])
    else neutralDates.push(date)
  }

  const dayOf = (p: any) => {
    const raw = Array.isArray(p.data) ? p.data : p.data?.value
    const date = raw?.[0]
    return date ? String(Number(String(date).slice(-2))) : ''
  }
  // 格子内两行：第一行日号，第二行当日收益率；无数据显示「—」
  const labelBase = calendarLabelBase(isDark.value, isMobile.value, {
    up: { color: isDark.value ? '#FF8B85' : '#B42318' },
    down: { color: isDark.value ? '#6FD1A5' : '#067647' },
    flat: { color: palette.neutralSub },
    closed: { color: palette.closedSub },
    outside: { color: palette.outsideSub },
  })
  const pnlLabel = {
    ...labelBase,
    color: isDark.value ? '#FAFAFA' : '#18181B',
    formatter: (p: any) => {
      const raw = Array.isArray(p.data) ? p.data : p.data?.value
      const ret = retMap.get(raw?.[0]) ?? 0
      const key = ret > 0 ? 'up' : ret < 0 ? 'down' : 'flat'
      const text = `${ret > 0 ? '+' : ''}${Number(ret).toFixed(1)}%`
      return `${dayOf(p)}\n{${key}|${text}}`
    },
  }
  // 无收益格子：日期数字也按层级降对比，本月无数据 > 休市 > 非本月
  const dashedLabel = (color: string, richKey: string) => ({
    ...labelBase,
    color,
    formatter: (p: any) => `${dayOf(p)}\n{${richKey}|—}`,
  })

  return {
    tooltip: {
      formatter: (p: any) => {
        const date = Array.isArray(p.data) ? p.data[0] : p.data.value[0]
        if (!date.startsWith(monthPrefix)) return `${date}<br/>非本月`
        if (closedDates.includes(date)) return `${date}<br/>休市`
        const ret = retMap.get(date)
        const amount = pnlAmountMap.value[date]
        const retText = ret !== undefined
          ? `当日收益: ${ret >= 0 ? '+' : ''}${Number(ret).toFixed(2)}%`
          : '暂无数据'
        const amountText = amount !== undefined
          ? `<br/>盈亏金额: ${amount >= 0 ? '+' : ''}¥${Number(amount).toFixed(2)}`
          : ''
        return `${date}<br/>${retText}${amountText}`
      },
      backgroundColor: isDark.value ? '#17171A' : '#FFFFFF',
      borderColor: isDark.value ? '#2A2A30' : '#E4E4E1',
      textStyle: { color: isDark.value ? '#FAFAFA' : '#18181B' },
    },
    visualMap: {
      min: -2, max: 2, show: true, orient: 'horizontal', left: 'center', bottom: 0,
      // 只给 0 号系列（本月有收益的交易日）着色，其他三层用固定底色
      seriesIndex: 0,
      // visualMap.text 为 [高端, 低端]：高端是盈利（红），低端是亏损（绿）
      inRange: { color: [lossColor, neutralColor, profitColor] },
      text: ['盈利', '亏损'],
      textStyle: { color: labelColor, fontSize: isMobile.value ? 9 : 12 },
      // 手机端默认色阶条厚 20px + 文字，会压在最后一行日期上，压成 8px 细条
      itemWidth: isMobile.value ? 8 : 20,
      itemHeight: isMobile.value ? 90 : 140,
    },
    calendar: {
      top: 32, left: 12, right: 12, range,
      // 七天横向排列（周日→周六），周向下排；horizontal 会把 6 周排成 6 列并把格子拉宽
      orient: 'vertical',
      // 列宽自适应卡片宽度，行高固定，日历不会再缩成 308px 的一小块
      cellSize: ['auto', isMobile.value ? 36 : isTablet.value ? 34 : 44],
      // 底层格子必须与卡片同色：否则圆角缺口会露出中性色，在格子交叉处形成杂色斑点
      itemStyle: { ...cellStyle, color: calendarSurfaceColor(isDark.value) },
      dayLabel: {
        firstDay: 0, nameMap: ['日', '一', '二', '三', '四', '五', '六'],
        color: labelColor, margin: isMobile.value ? 8 : 10, fontSize: isMobile.value ? 10 : 12,
      },
      monthLabel: { show: false },
      splitLine: { show: false },
    },
    series: [
      {
        // 本月交易日且有收益：颜色由 visualMap 决定
        type: 'heatmap', coordinateSystem: 'calendar', data: pnlData,
        itemStyle: { ...cellStyle },
        emphasis: { itemStyle: emphasisStyle },
        label: pnlLabel,
      },
      {
        // 本月交易日但无收益数据
        type: 'heatmap', coordinateSystem: 'calendar',
        data: neutralDates.map(d => [d, 0]),
        itemStyle: { ...cellStyle, color: neutralColor },
        emphasis: { itemStyle: emphasisStyle },
        label: dashedLabel(palette.neutralDate, 'flat'),
      },
      {
        // 本月休市：真实交易日历判定，比交易日浅一档
        type: 'heatmap', coordinateSystem: 'calendar',
        data: closedDates.map(d => [d, 0]),
        itemStyle: { ...cellStyle, color: closedColor },
        emphasis: { itemStyle: emphasisStyle },
        label: dashedLabel(palette.closedDate, 'closed'),
      },
      {
        // 非本月：最浅，visualMap.seriesIndex 只作用于 0，这里不会被染色
        type: 'heatmap', coordinateSystem: 'calendar',
        data: outsideDates.map(d => [d, 0]),
        itemStyle: { ...cellStyle, color: outsideColor },
        emphasis: { itemStyle: emphasisStyle },
        label: dashedLabel(palette.outsideDate, 'outside'),
      },
    ],
  }
})

const pnlAmountMap = computed(() => {
  const m: Record<string, number> = {}
  dailyPnlData.value.forEach(d => { m[d.date] = d.daily_pnl_amount })
  return m
})

const attributionChartOption = computed(() => {
  const c = themeColors.value
  return {
    tooltip: {
      trigger: 'item', formatter: '{b}: ¥{c} ({d}%)',
      backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: c.text },
    },
    legend: {
      orient: 'horizontal', left: 'center', bottom: 0, type: 'scroll',
      textStyle: { color: c.textSub },
    },
    series: [{
      type: 'pie', radius: ['38%', '62%'], center: ['50%', '46%'],
      data: attributionData.value.length > 0
        ? attributionData.value.map((a: any) => ({ name: a.sector_name, value: +a.contribution }))
        : [{ name: '暂无数据', value: 1 }],
      emphasis: { itemStyle: { shadowBlur: 10 } },
      label: { show: false },
      labelLine: { show: false },
    }],
  }
})

function loadSummary() {
  fundApi.getAccountSummary().then(summary => {
    summaryItems.value[0].value = `¥${(summary.total_assets / 10000).toFixed(2)}万`
    summaryItems.value[1].value = `¥${(summary.cash / 10000).toFixed(2)}万`
    summaryItems.value[2].value = `¥${(summary.market_value / 10000).toFixed(2)}万`
    summaryItems.value[3].value = `¥${summary.today_pnl?.toFixed(0) || 0}`
    summaryItems.value[4].value = `${((summary.cumulative_return || 0) * 100).toFixed(2)}%`
  }).catch(() => {})
}

function loadPositions() {
  fundApi.getPositions(positionStrategy.value || undefined).then(data => {
    positions.value = data
  }).catch(() => {})
}

function loadProfitCurve() {
  fundApi.getProfitCurve(parseInt(curveMonths.value)).then(data => {
    profitCurveData.value = data
    navData.value = data.nav_curve
  }).catch(() => {})
}

async function loadDailyPnl() {
  // 交易日历全局只拉一次；computed 里 isTradeDay 读取的 ref 会触发响应式重算
  await ensureTradeDates()
  fundApi.getDailyPnl(calendarMonth.value).then(data => {
    dailyPnlData.value = data
  }).catch(() => {})
}

function loadAttribution() {
  const end = dayjs().format('YYYY-MM-DD')
  const start = dayjs().subtract(3, 'month').format('YYYY-MM-DD')
  fundApi.getReturnAttribution({ strategyType: '', startDate: start, endDate: end }).then(data => {
    attributionData.value = data
  }).catch(() => {})
}

function loadTransfers() {
  fundApi.getTransfers().then(data => {
    transfers.value = data
  }).catch(() => {})
}

function submitTransfer() {
  if (!transferForm.date || !transferForm.amount) {
    ElMessage.warning('请填写完整信息')
    return
  }
  fundApi.createTransfer({
    transfer_date: transferForm.date,
    direction: transferForm.direction,
    amount: transferForm.amount,
    remark: transferForm.remark,
  }).then(() => {
    ElMessage.success('转账记录已添加')
    showTransferDialog.value = false
    transferForm.amount = 100000
    transferForm.remark = ''
    loadTransfers()
    loadSummary()
  }).catch((e) => {
    ElMessage.error(e?.message || '创建失败')
  })
}

function deleteTransfer(id: number) {
  ElMessageBox.confirm('确认删除此转账记录？', '提示', { type: 'warning' }).then(() => {
    fundApi.deleteTransfer(id).then(() => {
      ElMessage.success('已删除')
      loadTransfers()
      loadSummary()
    }).catch(() => {})
  }).catch(() => {})
}

onMounted(() => {
  loadSummary()
  loadPositions()
  loadProfitCurve()
  loadDailyPnl()
  loadAttribution()
  loadTransfers()
})
</script>

<style lang="scss" scoped>
/* 同一行卡片等高，图表 flex 填充，消除模块错落 */
.chart-row { align-items: stretch; }
.chart-row > :deep(.el-col) { display: flex; }
.chart-row > :deep(.el-col) > .page-card {
  display: flex;
  flex-direction: column;
  flex: 1;
  width: 100%;
}
.fill-chart { flex: 1; min-height: 0; width: 100%; }
.nav-chart { min-height: var(--chart-h-md); }
/* 七天横向日历：桌面 44px × 6 行 = 264，加星期头/色阶约 320；平板与手机用 34/36px 格子 */
.calendar-chart { min-height: var(--chart-h-lg); height: var(--chart-h-lg); }

.summary-row { margin-bottom: 16px; }
.summary-card {
  padding: 18px 16px; text-align: center;
  background: var(--bg-surface);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-md);
  transition: border-color var(--dur-fast) var(--ease);
  &:hover { border-color: var(--accent-primary); }
  .summary-label { font-size: 12px; color: var(--text-tertiary); margin-bottom: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .summary-value { font-size: 24px; font-weight: 600; font-family: var(--font-mono); letter-spacing: -.03em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
.stats-row { margin-top: 12px; flex-shrink: 0; }
.stat-item {
  text-align: center; padding: 8px;
  background: var(--bg-tertiary); border-radius: var(--radius-sm);
  .stat-label { font-size: 12px; color: var(--text-tertiary); display: block; }
  .stat-val { font-size: 15px; font-weight: 600; }
}

/* ─── 手机端列表（转账 / 持仓） ─── */
.m-list, .m-pos-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.m-list-row {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }
}

.m-row-main {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;

  .m-row-date { font-size: 12px; color: var(--text-secondary); font-family: var(--font-mono); }
  .m-row-amount { font-size: 13px; font-weight: 600; font-family: var(--font-mono); }
}

.m-row-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 3px;
  font-size: 10px;
  color: var(--text-tertiary);

  .m-row-remark {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.m-pos-card {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }
}

.m-pos-head {
  display: flex;
  align-items: center;
  gap: 6px;

  .m-pos-sector {
    flex: 1;
    min-width: 0;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .m-pos-pnl { font-size: 12px; font-weight: 600; font-family: var(--font-mono); }
}

.m-pos-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 4px;
  margin-top: 6px;

  & > div {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
    padding: 4px 5px;
    background: var(--bg-tertiary);
    border-radius: 4px;

    em { font-style: normal; font-size: 10px; color: var(--text-tertiary); }
    b { font-size: 11px; font-weight: 600; font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; }
  }
}

.m-pos-foot {
  margin-top: 5px;
  font-size: 10px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.m-list-empty {
  padding: 22px 0;
  text-align: center;
  font-size: 11px;
  color: var(--text-tertiary);
}

@media (max-width: 768px) {
  .summary-card {
    padding: 12px 8px;
    .summary-value { font-size: 16px; }
    .summary-label { font-size: 11px; }
  }
  .summary-row :deep(.el-col) { margin-bottom: 8px; }
  .stat-item { padding: 6px; .stat-val { font-size: 13px; } }
  .stats-row :deep(.el-col) { margin-bottom: 6px; }
  :deep(.el-row) { margin-left: -8px !important; margin-right: -8px !important; }
  :deep(.el-col) { padding-left: 8px !important; padding-right: 8px !important; }
  /* 单列堆叠后卡片失去等高约束，图表必须有确定高度，否则 flex:1 会塌成 0 */
  .fill-chart { flex: none; height: var(--chart-h-sm); min-height: var(--chart-h-sm); }
  .nav-chart { height: var(--chart-h-sm); }
  /* 34/36px 格子 × 6 行 + 月份头 28 + 星期头 20 + 色阶 20 ≈ 280 */
  .calendar-chart { height: 280px; min-height: 280px; }
}

@media (max-width: 480px) {
  .summary-card {
    padding: 8px 6px;
    .summary-value { font-size: 14px; }
    .summary-label { font-size: 10px; margin-bottom: 3px; }
  }
  .stat-item { padding: 5px 3px; .stat-val { font-size: 12px; } .stat-label { font-size: 10px; } }
  :deep(.el-row) { margin-left: -4px !important; margin-right: -4px !important; }
  :deep(.el-col) { padding-left: 4px !important; padding-right: 4px !important; }

  .chart-row :deep(.el-col) { margin-bottom: 8px; }
  .stats-row { margin-top: 6px; }

  .page-card .card-header :deep(.el-form) { width: 100%; }
  .page-card .card-header :deep(.el-form-item) { margin-bottom: 0; }
}
</style>
