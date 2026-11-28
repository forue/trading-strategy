<template>
  <div class="data-replay-page">
    <!-- 回放模式切换 + 时间范围 -->
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">板块交易数据回放</span>
        <el-tag v-if="dataAvailability.has_data" size="small" type="success">
          数据: {{ dataAvailability.min_date }} ~ {{ dataAvailability.max_date }}
        </el-tag>
      </div>

      <!-- 回放模式 Tabs -->
      <el-tabs v-model="replayMode" @tab-change="onModeChange">
        <el-tab-pane label="按日期回放" name="byDate">
          <div class="replay-controls">
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              :disabled-date="disableDate"
              class="control-date-range"
              @change="onDateRangeChange"
            />
            <el-select v-model="selectedSector" placeholder="全部板块" clearable filterable style="width: 160px" @change="onSectorFilterChange">
              <el-option v-for="s in sectorList" :key="s.sector_code" :label="s.sector_name" :value="s.sector_code" />
            </el-select>

            <el-divider direction="vertical" />

            <el-button @click="stepBackward" :disabled="currentDateIndex <= 0 || loading" size="default">
              <el-icon><ArrowLeft /></el-icon> 前一日
            </el-button>
            <el-date-picker
              v-model="selectedDate"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择日期"
              :disabled-date="disableDate"
              @change="onDateChange"
              style="width: 150px"
            />
            <el-button @click="stepForward" :disabled="currentDateIndex >= availableDates.length - 1 || loading" size="default">
              后一日 <el-icon><ArrowRight /></el-icon>
            </el-button>

            <el-divider direction="vertical" />

            <el-button type="primary" @click="loadDayData" :loading="loading" size="default">加载</el-button>
            <el-button :type="autoPlaying ? 'danger' : 'success'" @click="toggleAutoPlay" size="default">
              {{ autoPlaying ? '停止' : '自动播放' }}
            </el-button>
            <span style="color: #909399; font-size: 13px; margin-left: 4px">间隔:</span>
            <el-input-number v-model="playSpeed" :min="0.5" :max="10" :step="0.5" size="default" style="width: 90px" />
            <span style="color: #909399; font-size: 13px">秒</span>

            <div v-if="currentDateIndex >= 0" class="date-progress">
              {{ currentDateIndex + 1 }} / {{ availableDates.length }}
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="按板块回放" name="bySector">
          <div class="replay-controls">
            <el-select v-model="selectedSectorForHistory" placeholder="选择板块" filterable class="control-select-wide" @change="onSectorHistoryChange">
              <el-option v-for="s in sectorList" :key="s.sector_code" :label="`${s.sector_name} (${s.sector_code})`" :value="s.sector_code" />
            </el-select>
            <el-date-picker
              v-model="sectorDateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              class="control-date-range"
              @change="loadSectorHistory"
            />
            <el-button type="primary" @click="loadSectorHistory" :loading="sectorLoading" size="default">加载历史</el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="策略叠加回放" name="strategyOverlay">
          <div class="replay-controls">
            <el-date-picker
              v-model="overlayDateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              class="control-date-range"
            />
            <el-select v-model="overlayStrategyType" placeholder="选择策略" class="control-select-small">
              <el-option label="激进轮动" value="AGGRESSIVE" />
              <el-option label="稳健轮动" value="MODERATE" />
              <el-option label="保守轮动" value="CONSERVATIVE" />
            </el-select>
            <el-checkbox v-model="autoOptimize" :disabled="overlayLoading">自动寻优</el-checkbox>
            <el-input-number v-model="overlayCapital" :min="100000" :max="100000000" :step="100000" :controls="false" class="control-input-num" placeholder="初始资金" />
            <el-input-number v-if="autoOptimize" v-model="nTrials" :min="20" :max="200" :step="10" class="control-input-num-small" placeholder="试验次数" />
            <el-button type="primary" @click="loadStrategyOverlay" :loading="overlayLoading" size="default">
              {{ autoOptimize ? '自动寻优' : '运行策略回放' }}
            </el-button>
            <el-tag v-if="overlayLoading && autoOptimize" size="small" type="warning">
              寻优进度: {{ optimizationProgress }}/{{ totalCombinations }}
              （{{ nTrials }} 次试验 + 1 次样本外验证）
              ({{ totalCombinations > 0 ? Math.round(optimizationProgress / totalCombinations * 100) : 0 }}%)
            </el-tag>
          </div>

          <!-- 寻优结果：试验明细按试验序号倒序（最新试验置顶），分页应对大量试验 -->
          <div v-if="optimizeResult" ref="optimizeResultRef" class="optimize-result">
            <div class="card-header">
              <span class="card-title">
                寻优结果 · {{ optimizeResult.created_at }} · {{ optimizeResult.strategy_type }} ·
                {{ optimizeResult.all_results?.length || 0 }}/{{ optimizeResult.n_trials }} 次有效试验
              </span>
            </div>
            <el-row :gutter="12" class="stats-row">
              <el-col :xs="12" :sm="6" v-for="s in optimizeSummary" :key="s.label">
                <div class="stat-item">
                  <span class="stat-label">{{ s.label }}</span>
                  <span class="stat-val">{{ s.value }}</span>
                </div>
              </el-col>
            </el-row>
            <div v-if="optimizeResult.combined_summary" class="best-params">
              <span class="stat-label">指标口径：</span>
              <el-tag size="small" type="success" style="margin-right: 6px">全区间（含样本外）</el-tag>
              <span class="stat-label" style="margin-left: 8px">
                {{ optimizeResult.combined_summary.trading_days }} 个交易日
              </span>
            </div>
            <div v-if="optimizeResult.out_of_sample" class="best-params">
              <span class="stat-label">区间切分：</span>
              <el-tag size="small" type="info" style="margin-right: 6px">
                训练集 {{ optimizeResult.train_range?.join(' ~ ') }}
              </el-tag>
              <el-tag size="small" type="warning">
                样本外 {{ optimizeResult.oos_range?.join(' ~ ') }}（列表已拼接为完整区间）
              </el-tag>
            </div>
            <div v-if="optimizeResult.best_params" class="best-params">
              <span class="stat-label">最优参数：</span>
              <el-tag v-for="(v, k) in optimizeResult.best_params" :key="k" size="small" style="margin: 2px 6px 2px 0">
                {{ k }}: {{ v }}
              </el-tag>
            </div>
          </div>

          <!-- 历史寻优记录：后端按完成时间倒序返回，最新置顶 -->
          <div v-if="optimizeHistory.length" class="optimize-history">
            <div class="card-header">
              <span class="card-title">历史寻优记录（最新在前）</span>
            </div>
            <!-- 手机端：七列历史表改为记录条目 -->
            <ul v-if="bp.isMobile.value" class="m-hist-list">
              <li v-for="(row, hi) in pagedHistory" :key="hi" class="m-hist-row">
                <div class="m-hist-head">
                  <span class="m-hist-time">{{ row.created_at }}</span>
                  <el-tag size="small">{{ row.strategy_type }}</el-tag>
                </div>
                <div class="m-hist-grid">
                  <div><em>总收益</em><b :style="{ color: row.total_return >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">{{ (row.total_return * 100).toFixed(2) }}%</b></div>
                  <div><em>最大回撤</em><b>{{ (row.max_drawdown * 100).toFixed(2) }}%</b></div>
                  <div><em>夏普</em><b>{{ row.sharpe_ratio }}</b></div>
                  <div><em>试验</em><b>{{ row.n_trials }}</b></div>
                </div>
                <div class="m-hist-range">{{ row.train_range?.join(' ~ ') || '--' }}</div>
                <button class="m-hist-detail" @click="viewHistoryDetail(row)">查看详情</button>
              </li>
            </ul>

            <div v-else class="responsive-table">
              <el-table :data="pagedHistory" stripe size="small" style="width: 100%">
                <el-table-column prop="created_at" label="完成时间" width="160" />
                <el-table-column prop="strategy_type" label="策略" width="96" />
                <el-table-column prop="n_trials" label="试验次数" width="96" align="right" />
                <el-table-column label="总收益" width="96" align="right">
                  <template #default="{ row }">{{ (row.total_return * 100).toFixed(2) }}%</template>
                </el-table-column>
                <el-table-column label="最大回撤" width="96" align="right">
                  <template #default="{ row }">{{ (row.max_drawdown * 100).toFixed(2) }}%</template>
                </el-table-column>
                <el-table-column prop="sharpe_ratio" label="夏普" width="96" align="right" />
                <el-table-column label="训练区间" min-width="180">
                  <template #default="{ row }">{{ row.train_range?.join(' ~ ') || '--' }}</template>
                </el-table-column>
                <el-table-column label="操作" width="96" fixed="right">
                  <template #default="{ row }">
                    <el-button link type="primary" size="small" @click="viewHistoryDetail(row)">查看详情</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <el-pagination
              v-model:current-page="histPage"
              v-model:page-size="histSize"
              :total="optimizeHistory.length"
              :page-sizes="[10, 20]"
              layout="total, sizes, prev, pager, next"
              class="table-pagination"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- ============ 按日期回放 ============ -->
    <div v-if="replayMode === 'byDate' && dayData" class="page-card page-section">
      <div class="card-header">
        <span class="card-title">{{ dayData.date }} 板块数据</span>
        <el-tag size="small">{{ dayData.count }} 个板块</el-tag>
      </div>

      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :xs="12" :sm="6">
          <div class="stat-box rise"><div class="stat-value">{{ riseCount }}</div><div class="stat-label">上涨板块</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box fall"><div class="stat-value">{{ fallCount }}</div><div class="stat-label">下跌板块</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ avgChangeStr }}</div><div class="stat-label">平均涨跌幅</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box">
            <div class="stat-value name" :style="{ color: maxRiseSector?.index_change_pct >= 0 ? '#f56c6c' : '#67c23a' }">
              {{ maxRiseSector?.sector_name || '-' }}
            </div>
            <div class="stat-label">领涨板块 {{ maxRiseSector ? (maxRiseSector.index_change_pct >= 0 ? '+' : '') + maxRiseSector.index_change_pct.toFixed(2) + '%' : '' }}</div>
          </div>
        </el-col>
      </el-row>

      <v-chart v-if="dayData?.date" :option="flowChartOption" :key="`flow-${dayData.date}`" class="flow-chart" autoresize />
      <div v-else class="flow-chart chart-placeholder">
        加载中...
      </div>

      <!-- 手机端：六列板块数据改为「名称+涨跌幅 / 指标网格」条目 -->
      <ul v-if="bp.isMobile.value" class="m-sector-data">
        <li v-for="row in sortedDaySectors" :key="row.sector_code" class="m-sector-data-row">
          <div class="m-sd-head">
            <span class="m-sd-name">{{ row.sector_name }}</span>
            <span class="m-sd-change" :style="{ color: row.index_change_pct >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
              {{ row.index_change_pct >= 0 ? '+' : '' }}{{ row.index_change_pct.toFixed(2) }}%
            </span>
          </div>
          <div class="m-sd-grid">
            <div><em>收盘指数</em><b>{{ row.index_close?.toFixed(2) }}</b></div>
            <div><em>主力净流入</em><b :style="{ color: row.main_net_inflow >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">{{ (row.main_net_inflow / 1e8).toFixed(2) }}亿</b></div>
            <div><em>成交额</em><b>{{ (row.turnover / 1e8).toFixed(2) }}亿</b></div>
          </div>
        </li>
      </ul>

      <div v-else class="responsive-table"><el-table :data="dayData.sectors" stripe size="small" style="margin-top: 16px" :default-sort="{ prop: 'index_change_pct', order: 'descending' }">
        <el-table-column prop="sector_name" label="板块" width="120" fixed />
        <el-table-column prop="index_change_pct" label="涨跌幅" min-width="96" sortable align="right">
          <template #default="{ row }">
            <span :class="row.index_change_pct >= 0 ? 'signal-buy' : 'signal-sell'">
              {{ row.index_change_pct >= 0 ? '+' : '' }}{{ row.index_change_pct.toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="index_close" label="收盘指数" min-width="96" align="right">
          <template #default="{ row }">{{ row.index_close?.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="main_net_inflow" label="主力净流入(亿)" min-width="120" sortable align="right">
          <template #default="{ row }">
            <span :style="{ color: row.main_net_inflow >= 0 ? '#f56c6c' : '#67c23a' }">{{ (row.main_net_inflow / 1e8).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <!-- 北向资金数据源已停止披露，列置灰停用 -->
        <el-table-column prop="north_net_inflow" label="北向净流入(亿)" min-width="140" sortable label-class-name="col-disabled" class-name="col-disabled" align="right">
          <template #header>
            <el-tooltip content="沪深港通自 2024-08-19 起停止披露北向资金净买额，该列已停用" placement="top">
              <span>北向净流入(亿)<el-tag size="small" type="info" effect="plain">已停用</el-tag></span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <span class="disabled-text">{{ (row.north_net_inflow / 1e8).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="turnover" label="成交额(亿)" min-width="110" sortable align="right">
          <template #default="{ row }">{{ (row.turnover / 1e8).toFixed(2) }}</template>
        </el-table-column>
      </el-table></div>
    </div>

    <div v-else-if="replayMode === 'byDate' && !loading" class="page-card page-section">
      <el-empty description="请选择时间范围并点击加载" />
    </div>

    <!-- ============ 按板块回放 ============ -->
    <div v-if="replayMode === 'bySector' && sectorHistory.length > 0" class="page-card page-section">
      <div class="card-header">
        <span class="card-title">{{ currentSectorName }} 历史数据</span>
        <el-tag size="small">{{ sectorHistory.length }} 个交易日 · {{ periodLabel }}K</el-tag>
      </div>

      <div class="kline-toolbar">
        <el-radio-group v-model="klinePeriod" size="small" class="kline-period fill">
          <el-radio-button value="day">日K</el-radio-button>
          <el-radio-button value="week">周K</el-radio-button>
          <el-radio-button value="month">月K</el-radio-button>
          <el-radio-button value="quarter">季K</el-radio-button>
        </el-radio-group>
        <div class="kline-ma" :class="{ 'ma-hidden': asLine }">
          <button v-for="m in maSeries" :key="m.key" type="button" class="ma-toggle" :class="{ active: maVisible[m.key] }" @click="maVisible[m.key] = !maVisible[m.key]">
            <i class="ma-dot" :style="{ background: m.color }" />{{ m.key.toUpperCase() }}
          </button>
          <span class="kline-legend-note"><i class="flow-dot" />主力净流入</span>
          <span class="kline-legend-note disabled">北向 · 已停用</span>
        </div>
      </div>

      <v-chart ref="sectorChartRef" :option="sectorHistoryChartOption" class="sector-history-chart" autoresize @datazoom="onKlineDataZoom" />
      <p v-if="bp.isMobile.value" class="kline-gesture-tip">
        {{ asLine ? 'K线过密，已切折线模式 · 左右滑动浏览 · 双指捏合缩放' : '左右滑动浏览 · 双指捏合缩放 · 长按查看数据' }}
      </p>

      <el-row :gutter="16" style="margin-top: 12px">
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.totalReturn }}</div><div class="stat-label">区间涨跌幅</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.maxRise }}</div><div class="stat-label">最大单日涨幅</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.maxFall }}</div><div class="stat-label">最大单日跌幅</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.avgChange }}</div><div class="stat-label">日均涨跌幅</div></div>
        </el-col>
      </el-row>

      <!-- 手机端：交易日历史同样改为条目（最新交易日在最前） -->
      <ul v-if="bp.isMobile.value" class="m-sector-data">
        <li v-for="row in sectorHistoryRows" :key="row.date" class="m-sector-data-row">
          <div class="m-sd-head">
            <span class="m-sd-name">{{ row.date }}</span>
            <span class="m-sd-change" :style="{ color: row.index_change_pct >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
              {{ row.index_change_pct >= 0 ? '+' : '' }}{{ row.index_change_pct.toFixed(2) }}%
            </span>
          </div>
          <div class="m-sd-grid">
            <div><em>收盘指数</em><b>{{ row.index_close?.toFixed(2) }}</b></div>
            <div><em>主力净流入</em><b :style="{ color: row.main_net_inflow >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">{{ (row.main_net_inflow / 1e8).toFixed(2) }}亿</b></div>
            <div><em>成交额</em><b>{{ (row.turnover / 1e8).toFixed(2) }}亿</b></div>
          </div>
        </li>
      </ul>

      <div v-else class="responsive-table"><el-table :data="sectorHistoryRows" stripe size="small" style="margin-top: 16px">
        <el-table-column prop="date" label="日期" width="120" sortable />
        <el-table-column prop="index_change_pct" label="涨跌幅" min-width="96" sortable align="right">
          <template #default="{ row }">
            <span :class="row.index_change_pct >= 0 ? 'signal-buy' : 'signal-sell'">{{ row.index_change_pct >= 0 ? '+' : '' }}{{ row.index_change_pct.toFixed(2) }}%</span>
          </template>
        </el-table-column>
        <el-table-column prop="index_close" label="收盘指数" min-width="96" align="right">
          <template #default="{ row }">{{ row.index_close?.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="main_net_inflow" label="主力净流入(亿)" min-width="120" sortable align="right">
          <template #default="{ row }">
            <span :style="{ color: row.main_net_inflow >= 0 ? '#f56c6c' : '#67c23a' }">{{ (row.main_net_inflow / 1e8).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <!-- 北向资金数据源已停止披露，列置灰停用 -->
        <el-table-column prop="north_net_inflow" label="北向净流入(亿)" min-width="140" sortable label-class-name="col-disabled" class-name="col-disabled" align="right">
          <template #header>
            <el-tooltip content="沪深港通自 2024-08-19 起停止披露北向资金净买额，该列已停用" placement="top">
              <span>北向净流入(亿)<el-tag size="small" type="info" effect="plain">已停用</el-tag></span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <span class="disabled-text">{{ (row.north_net_inflow / 1e8).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="turnover" label="成交额(亿)" min-width="110" sortable align="right">
          <template #default="{ row }">{{ (row.turnover / 1e8).toFixed(2) }}</template>
        </el-table-column>
      </el-table></div>
    </div>

    <div v-else-if="replayMode === 'bySector' && !sectorLoading" class="page-card page-section">
      <el-empty description="请选择板块并点击加载历史" />
    </div>

    <!-- ============ 策略叠加回放 ============ -->
    <div v-if="replayMode === 'strategyOverlay' && overlayData" class="page-card page-section">
      <!-- 策略参数显示 -->
      <div v-if="overlayData.summary.params" class="params-display">
        <el-tag size="small" type="info">参数: top_n={{ overlayData.summary.params.top_n }}, 持仓={{ overlayData.summary.params.max_position * 100 }}%, 持有={{ overlayData.summary.params.hold_days }}日, 止损={{ overlayData.summary.params.stop_loss * 100 }}%, 评分阈值={{ overlayData.summary.params.min_score_threshold }}, 评分差={{ overlayData.summary.params.score_gap_threshold }}, 冷却={{ overlayData.summary.params.cooldown_days }}日</el-tag>
      </div>

      <!-- 策略收益概览 -->
      <div class="card-header">
        <span class="card-title">{{ overlayStrategyLabel }} 回放结果</span>
        <el-tag size="small">{{ overlayData.summary.trading_days }} 个交易日</el-tag>
      </div>

      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box" :class="{ rise: overlayData.summary.total_return >= 0, fall: overlayData.summary.total_return < 0 }">
            <div class="stat-value">{{ (overlayData.summary.total_return >= 0 ? '+' : '') + (overlayData.summary.total_return * 100).toFixed(2) }}%</div>
            <div class="stat-label">总收益</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box" :class="{ rise: overlayData.summary.annual_return >= 0, fall: overlayData.summary.annual_return < 0 }">
            <div class="stat-value">{{ (overlayData.summary.annual_return >= 0 ? '+' : '') + (overlayData.summary.annual_return * 100).toFixed(2) }}%</div>
            <div class="stat-label">年化收益</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box fall">
            <div class="stat-value">{{ (overlayData.summary.max_drawdown * 100).toFixed(2) }}%</div>
            <div class="stat-label">最大回撤</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box rise">
            <div class="stat-value">{{ overlayData.summary.buy_count }}</div>
            <div class="stat-label">买入信号</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box fall">
            <div class="stat-value">{{ overlayData.summary.sell_count }}</div>
            <div class="stat-label">卖出信号</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box">
            <div class="stat-value">{{ formatMoney(overlayData.summary.final_capital) }}</div>
            <div class="stat-label">最终资产(万)</div>
          </div>
        </el-col>
      </el-row>

      <!-- 策略净值曲线 + 买卖点标记（桌面 420px，移动端走 7.5.3 高度令牌） -->
      <v-chart
        ref="overlayChartRef"
        :option="overlayChartOption"
        class="overlay-chart"
        autoresize
        @datazoom="onOverlayZoom"
      />

      <!-- 每日信号明细 -->
      <div style="margin-top: 16px">
        <div class="card-header" style="margin-bottom: 8px">
          <span style="font-weight: 600">每日持仓明细</span>
          <el-tag size="small">{{ overlaySignalDays.length }} 个交易日</el-tag>
        </div>
        <!-- 手机端：九列持仓表改为「日期+收益 / 持仓 / 信号 / 资产网格」条目 -->
        <ul v-if="bp.isMobile.value" class="m-overlay-day-list">
          <li v-for="row in overlaySignalDays" :key="row.date" class="m-od-row">
            <div class="m-od-head">
              <span class="m-od-date">{{ row.date }}</span>
              <span class="m-od-return" :style="{ color: row.strategy_return >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
                {{ row.strategy_return >= 0 ? '+' : '' }}{{ row.strategy_return.toFixed(2) }}%
              </span>
            </div>
            <div class="m-od-positions">
              <template v-if="row.positions.length">
                <span v-for="p in row.positions" :key="p.sector_code" class="m-od-position">
                  {{ p.etf_name || p.sector_name }} {{ (p.weight * 100).toFixed(1) }}%
                </span>
              </template>
              <span v-else class="m-od-empty">空仓</span>
            </div>
            <div class="m-od-signals">
              <el-tag v-for="sig in row.buySignals" :key="`b-${sig.sector_code}`" size="small" type="danger">买 {{ sig.sector_name }}</el-tag>
              <el-tag v-for="sig in row.sellSignals" :key="`s-${sig.sector_code}`" size="small" type="success">卖 {{ sig.sector_name }}</el-tag>
              <span v-if="!row.buySignals.length && !row.sellSignals.length" class="m-od-empty">
                {{ row.status === 'EMPTY' ? '空仓观望' : (row.status === 'HOLD' ? '持有不动' : '-') }}
              </span>
            </div>
            <div class="m-od-grid">
              <div><em>基准日收益</em><b>{{ row.benchmark_return >= 0 ? '+' : '' }}{{ row.benchmark_return.toFixed(2) }}%</b></div>
              <div><em>持仓市值</em><b>{{ formatOverlayMoney(row.total_position_value) }}</b></div>
              <div><em>现金</em><b>{{ formatOverlayMoney(row.cash) }}</b></div>
              <div><em>总资产</em><b>{{ formatOverlayMoney(row.total_asset) }}</b></div>
            </div>
          </li>
        </ul>
        <div v-else class="responsive-table"><el-table :data="overlaySignalDays" stripe size="small" max-height="500">
          <el-table-column prop="date" label="日期" width="110" sortable fixed />
          <el-table-column label="持仓" min-width="260">
            <template #default="{ row }">
              <template v-if="row.positions.length">
                <div v-for="p in row.positions" :key="p.sector_code" class="holding-item">
                  <span class="holding-etf">{{ p.etf_code || p.sector_code }} {{ p.etf_name || p.sector_name }}</span>
                  <span class="holding-meta">{{ (p.weight * 100).toFixed(1) }}% {{ formatOverlayMoney(p.amount) }}</span>
                </div>
              </template>
              <span v-else style="color: var(--text-tertiary)">空仓</span>
            </template>
          </el-table-column>
          <el-table-column label="买入" min-width="140">
            <template #default="{ row }">
              <el-tag v-for="sig in row.buySignals" :key="sig.sector_code" size="small" type="danger" style="margin: 1px">
                {{ sig.sector_name }}
              </el-tag>
              <span v-if="!row.buySignals.length" style="color: var(--text-tertiary)">
                {{ row.status === 'EMPTY' ? '空仓观望' : (row.status === 'HOLD' ? '持有不动' : '-') }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="卖出" min-width="140">
            <template #default="{ row }">
              <el-tag v-for="sig in row.sellSignals" :key="sig.sector_code" size="small" type="success" style="margin: 1px">
                {{ sig.sector_name }}
              </el-tag>
              <span v-if="!row.sellSignals.length" style="color: var(--text-tertiary)">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="strategy_return" label="策略日收益" width="96" sortable align="right">
            <template #default="{ row }">
              <span :style="{ color: row.strategy_return >= 0 ? (isDark ? '#ff6f61' : '#f56c6c') : (isDark ? '#357a5c' : '#67c23a') }">
                {{ row.strategy_return >= 0 ? '+' : '' }}{{ row.strategy_return.toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="benchmark_return" label="基准日收益" width="96" align="right">
            <template #default="{ row }">
              <span style="color: var(--text-tertiary)">{{ row.benchmark_return >= 0 ? '+' : '' }}{{ row.benchmark_return.toFixed(2) }}%</span>
            </template>
          </el-table-column>
          <el-table-column prop="total_position_value" label="持仓市值" width="110" align="right">
            <template #default="{ row }">{{ formatOverlayMoney(row.total_position_value) }}</template>
          </el-table-column>
          <el-table-column prop="cash" label="现金" width="110">
            <template #default="{ row }">{{ formatOverlayMoney(row.cash) }}</template>
          </el-table-column>
          <el-table-column prop="total_asset" label="总资产" width="110" sortable>
            <template #default="{ row }">{{ formatOverlayMoney(row.total_asset) }}</template>
          </el-table-column>
        </el-table></div>
      </div>

      <!-- 调仓明细 -->
      <div v-if="overlayRebalanceGroups.length" style="margin-top: 16px">
        <div class="card-header" style="margin-bottom: 8px">
          <span style="font-weight: 600">调仓明细</span>
          <el-tag size="small">{{ overlayRebalanceGroups.length }} 个调仓日</el-tag>
        </div>
        <div v-for="group in overlayRebalanceGroups" :key="group.date" class="rebalance-group">
          <div class="rebalance-date-header">
            <span class="rebalance-date">{{ group.date }}</span>
            <el-tag size="small">{{ group.trades.length }} 笔调仓</el-tag>
          </div>
          <!-- 持仓快照：手机端改条目列表 -->
          <ul v-if="bp.isMobile.value && group.snapshot?.portfolio?.length" class="m-snap-list">
            <li v-for="p in group.snapshot.portfolio" :key="p.sector_code" class="m-snap-row">
              <div class="m-snap-head">
                <span class="m-snap-name">{{ p.sector_name || p.sector_code }}</span>
                <span class="m-snap-weight">{{ (p.weight * 100).toFixed(1) }}%</span>
              </div>
              <div class="m-snap-grid">
                <div><em>金额</em><b>{{ formatOverlayMoney(p.amount) }}</b></div>
                <div><em>当日涨跌</em><b :style="{ color: p.day_change_pct >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">{{ p.day_change_pct >= 0 ? '+' : '' }}{{ p.day_change_pct.toFixed(2) }}%</b></div>
                <div><em>贡献</em><b :style="{ color: p.contribution_pct >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">{{ p.contribution_pct >= 0 ? '+' : '' }}{{ p.contribution_pct.toFixed(2) }}%</b></div>
              </div>
            </li>
          </ul>
          <div v-else-if="group.snapshot?.portfolio?.length" class="responsive-table" style="margin: 8px 0">
            <el-table :data="group.snapshot.portfolio" stripe size="small" max-height="200">
              <el-table-column prop="sector_name" label="板块" min-width="120" />
              <el-table-column prop="weight" label="仓位" min-width="80" align="right">
                <template #default="{ row }">{{ (row.weight * 100).toFixed(1) }}%</template>
              </el-table-column>
              <el-table-column prop="amount" label="金额" min-width="96" align="right">
                <template #default="{ row }">{{ formatOverlayMoney(row.amount) }}</template>
              </el-table-column>
              <el-table-column prop="day_change_pct" label="当日涨跌" min-width="96" align="right">
                <template #default="{ row }">
                  <span :style="{ color: row.day_change_pct >= 0 ? '#f56c6c' : '#67c23a' }">
                    {{ row.day_change_pct >= 0 ? '+' : '' }}{{ row.day_change_pct.toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="contribution_pct" label="贡献" min-width="80" align="right">
                <template #default="{ row }">
                  <span :style="{ color: row.contribution_pct >= 0 ? '#f56c6c' : '#67c23a' }">
                    {{ row.contribution_pct >= 0 ? '+' : '' }}{{ row.contribution_pct.toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div v-else-if="group.snapshot && !group.snapshot.portfolio?.length" style="color:#909399;font-size:12px;margin:4px 0">空仓</div>
          <!-- 交易记录 -->
          <div class="rebalance-trades">
            <el-tag v-for="(t, idx) in group.trades" :key="idx" size="small"
              :type="overlayTradeTagType(t.action)" style="margin: 2px">
              {{ t.sector_name || t.sector_code }} {{ overlayActionLabel(t.action) }}
              <span v-if="t.amount > 0">{{ formatOverlayMoney(t.amount) }}</span>
              <span v-if="t.cost > 0" style="opacity:0.7"> (费{{ t.cost.toFixed(1) }})</span>
            </el-tag>
          </div>
          <div v-if="group.trades.length && group.trades[0].reason" style="color: #909399; font-size: 12px; margin-top: 4px">
            {{ group.trades[0].reason }}
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="replayMode === 'strategyOverlay' && !overlayLoading" class="page-card page-section">
      <el-empty description="请选择时间范围和策略，点击运行策略回放" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onUpdated, onUnmounted, nextTick } from 'vue'
import VChart from 'vue-echarts'
import { use, getInstanceByDom } from 'echarts/core'
import { BarChart, LineChart, ScatterChart, CandlestickChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent, MarkPointComponent, MarkAreaComponent, TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage } from 'element-plus'
import { settingsApi } from '@/api/settings'
import { strategyApi } from '@/api/strategy'
import { useThemeStore } from '@/stores/theme'
import { useStrategyStore } from '@/stores/strategy'
import { useReplayTaskStore } from '@/stores/replayTask'
import { useBreakpoint } from '@/composables/useBreakpoint'
import dayjs from 'dayjs'

const bp = useBreakpoint()
const strategyStore = useStrategyStore()
const replayTaskStore = useReplayTaskStore()

use([BarChart, LineChart, ScatterChart, CandlestickChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent, MarkPointComponent, MarkAreaComponent, TitleComponent, CanvasRenderer])

const themeStore = useThemeStore()
// 供模板使用的暗色标志（各图表 option 内部另有局部同名变量，不影响）
const isDark = computed(() => themeStore.mode === 'dark')

// ============ 通用状态 ============
const loading = ref(false)
const sectorLoading = ref(false)
const overlayLoading = ref(false)
const replayMode = ref<'byDate' | 'bySector' | 'strategyOverlay'>('byDate')
const sectorList = ref<{ sector_code: string; sector_name: string }[]>([])
const dataAvailability = reactive({ has_data: false, min_date: '', max_date: '' })

// ============ 按日期回放状态 ============
const dateRange = ref<string[]>([])
const selectedDate = ref('')
const selectedSector = ref('')
const availableDates = ref<string[]>([])
const currentDateIndex = ref(-1)
const dayData = ref<{ date: string; sectors: any[]; count: number } | null>(null)
const autoPlaying = ref(false)
const playSpeed = ref(1.5)
let autoPlayTimer: ReturnType<typeof setTimeout> | null = null

// ============ 按板块回放状态 ============
const selectedSectorForHistory = ref('')
const sectorDateRange = ref<string[]>([])
const sectorHistory = ref<any[]>([])

type KlinePeriod = 'day' | 'week' | 'month' | 'quarter'
type MaKey = 'ma5' | 'ma10' | 'ma20' | 'ma60'
const maSeries = [
  { key: 'ma5', period: 5, color: '#e6a23c' },
  { key: 'ma10', period: 10, color: '#909399' },
  { key: 'ma20', period: 20, color: '#409eff' },
  { key: 'ma60', period: 60, color: '#c45656' },
] as const
const klinePeriod = ref<KlinePeriod>('day')
const MIN_KLINE_BARS = 28 // 雪球式最小窗口：再放大就没有意义
const LINE_KLINE_BARS = 120 // 单根 K 线细于 3px 时改折线，避免蜡烛糊成一片
const klineSpan = ref(60)
// 当前缩放窗口百分比。必须是非响应式普通变量：拖动时每帧都会更新它，若是 ref 会让 option computed 重算并 setOption，
// 导致拖动卡顿/不即时绘制。option 只在 asLine、周期、数据等变化时重算，届时读取此变量的最新值即可。
let klineStart = 100
let klineEnd = 100
const asLine = computed(() => klineSpan.value > LINE_KLINE_BARS)
const periodLabel = computed(() => ({ day: '日', week: '周', month: '月', quarter: '季' })[klinePeriod.value])
const maVisible = ref<Record<MaKey, boolean>>({ ma5: true, ma10: true, ma20: true, ma60: false })

/** 按自然周/月/季聚合 K 线：开取首根、收取末根、高低取极值、资金流求和 */
function periodBucket(date: string, period: KlinePeriod): string {
  if (period === 'day') return date
  const d = new Date(`${date}T00:00:00`)
  if (period === 'week') {
    const monday = new Date(d)
    monday.setDate(d.getDate() - ((d.getDay() + 6) % 7))
    return `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, '0')}-${String(monday.getDate()).padStart(2, '0')}`
  }
  if (period === 'month') return date.slice(0, 7)
  return `${d.getFullYear()}-Q${Math.floor(d.getMonth() / 3) + 1}`
}

function aggregateHistory(rows: any[], period: KlinePeriod) {
  if (period === 'day') return rows
  const buckets = new Map<string, any[]>()
  for (const row of rows) {
    const key = periodBucket(row.date, period)
    const group = buckets.get(key)
    if (group) group.push(row)
    else buckets.set(key, [row])
  }
  const num = (v: any) => Number(v) || 0
  // 单日行可能缺 OHLC（收盘后只回填了资金流/估值，K 线还没采到），接口会给出 open/high/low = 0。
  // 0 参与极值会把低点压到 0，周/月/季最后一根会变成一根从 0 拉起的超长影线，
  // 故只接受 >0 的有效价，缺失时回退到当日收盘指数点位
  const pick = (...cands: any[]) => {
    for (const c of cands) {
      const v = Number(c)
      if (Number.isFinite(v) && v > 0) return v
    }
    return null
  }
  return [...buckets.values()].map((group) => {
    const first = group[0]
    const last = group[group.length - 1]
    const open = pick(first.open, first.index_close, first.close) ?? 0
    const close = pick(last.close, last.index_close, last.open) ?? open
    const highs = group.map(row => pick(row.high, row.index_close, row.close)).filter((v): v is number => v != null)
    const lows = group.map(row => pick(row.low, row.index_close, row.close)).filter((v): v is number => v != null)
    const sum = (field: string) => group.reduce((acc, row) => acc + num(row[field]), 0)
    return {
      ...last,
      open,
      close,
      // 高低点再与开收价兜底比较一次：日线缺少影线数据时，至少保证 high >= max(open, close) >= min(open, close) >= low
      high: highs.length ? Math.max(open, close, ...highs) : Math.max(open, close),
      low: lows.length ? Math.min(open, close, ...lows) : Math.min(open, close),
      index_close: close,
      index_change_pct: open ? ((close - open) / open) * 100 : 0,
      main_net_inflow: sum('main_net_inflow'),
      north_net_inflow: sum('north_net_inflow'),
      turnover: sum('turnover'),
    }
  })
}

const aggregatedHistory = computed(() => aggregateHistory(sectorHistory.value, klinePeriod.value))

// ============ 策略叠加回放状态 ============
const overlayDateRange = ref<string[]>([])
const overlayStrategyType = ref(strategyStore.currentStrategy as string)
const overlayCapital = ref(1000000)
const nTrials = ref(50)
const autoOptimize = ref(false)

// ===== 寻优结果展示 =====
const optimizeResult = ref<any>(null)
const optimizeHistory = ref<any[]>([])
const histPage = ref(1)
const histSize = ref(10)

// 历史记录：后端已按完成时间倒序（最新在前），此处仅分页
const pagedHistory = computed(() => {
  const start = (histPage.value - 1) * histSize.value
  return optimizeHistory.value.slice(start, start + histSize.value)
})

// 最近一次寻优的关键指标摘要
const optimizeSummary = computed(() => {
  const r = optimizeResult.value
  if (!r?.best_result) return []
  const b = r.best_result
  const oos = r.out_of_sample
  return [
    { label: '总收益', value: `${(b.total_return * 100).toFixed(2)}%` },
    { label: '最大回撤', value: `${(b.max_drawdown * 100).toFixed(2)}%` },
    { label: '夏普比率', value: `${b.sharpe_ratio}` },
    { label: '样本外收益', value: oos ? `${(oos.total_return * 100).toFixed(2)}%` : '--' },
  ]
})

const optimizeResultRef = ref<HTMLElement | null>(null)

async function loadOptimizeHistory() {
  try {
    optimizeHistory.value = await settingsApi.getOptimizeHistory() || []
  } catch {
    optimizeHistory.value = []
  }
}

// 查看历史寻优详情：后端按 id 返回完整结果归档，直接填回结果区展示
async function viewHistoryDetail(row: any) {
  const id = row.id || row.created_at
  try {
    const detail = await settingsApi.getOptimizeHistoryDetail(id)
    optimizeResult.value = detail
    // 寻优结果里的 best_result 是 _run_backtest_core(return_full=True) 的完整回测数据，
    // 需按叠加回放的嵌套格式转换，才能带出净值曲线、每日持仓明细与调仓快照。
    const full = detail.best_result || {}
    const { nav_curve, daily_signals, position_changes, portfolio_snapshots, ...summary } = full
    overlayData.value = {
      summary,
      nav_curve: nav_curve || [],
      daily_signals: daily_signals || [],
      position_changes: position_changes || [],
      portfolio_snapshots: portfolio_snapshots || [],
    }
    await nextTick()
    optimizeResultRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    ElMessage.success('已载入该次寻优详情')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '未知错误'
    ElMessage.error(`查看详情失败：${msg}`)
  }
}
const optimizationProgress = ref(0)
const totalCombinations = ref(0)
const bestParams = ref<any>(null)
const abortOptimize = ref(false)
const overlayData = ref<{
  daily_signals: any[]
  nav_curve: any[]
  summary: any
  position_changes: any[]
  portfolio_snapshots?: any[]
} | null>(null)

// ============ 计算属性 ============
const riseCount = computed(() => dayData.value?.sectors.filter(s => s.index_change_pct >= 0).length ?? 0)
const fallCount = computed(() => dayData.value?.sectors.filter(s => s.index_change_pct < 0).length ?? 0)
const avgChangeStr = computed(() => {
  if (!dayData.value?.sectors.length) return '-'
  const avg = dayData.value.sectors.reduce((sum, s) => sum + s.index_change_pct, 0) / dayData.value.sectors.length
  return (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%'
})
// 移动端列表沿用表格默认排序（涨跌幅降序）
const sortedDaySectors = computed(() =>
  [...(dayData.value?.sectors || [])].sort((a, b) => (b.index_change_pct ?? 0) - (a.index_change_pct ?? 0)),
)
const maxRiseSector = computed(() => {
  if (!dayData.value?.sectors.length) return null
  return [...dayData.value.sectors].sort((a, b) => b.index_change_pct - a.index_change_pct)[0]
})

const currentSectorName = computed(() => {
  const s = sectorList.value.find(x => x.sector_code === selectedSectorForHistory.value)
  return s?.sector_name || selectedSectorForHistory.value
})

// 表格展示按日期倒序：最近的交易日放在最前（图表仍用 sectorHistory 原始升序，避免 K 线错序）
const sectorHistoryRows = computed(() =>
  [...sectorHistory.value].sort((a: any, b: any) => String(b.date || '').localeCompare(String(a.date || '')))
)

const sectorStats = computed(() => {
  if (!sectorHistory.value.length) return { totalReturn: '-', maxRise: '-', maxFall: '-', avgChange: '-' }
  const changes = sectorHistory.value.map(s => s.index_change_pct)
  const total = changes.reduce((a, b) => a + b, 0)
  return {
    totalReturn: (total >= 0 ? '+' : '') + total.toFixed(2) + '%',
    maxRise: '+' + Math.max(...changes).toFixed(2) + '%',
    maxFall: Math.min(...changes).toFixed(2) + '%',
    avgChange: (total / changes.length >= 0 ? '+' : '') + (total / changes.length).toFixed(3) + '%',
  }
})

const overlayStrategyLabel = computed(() => {
  const map: Record<string, string> = { AGGRESSIVE: '激进轮动', MODERATE: '稳健轮动', CONSERVATIVE: '保守轮动' }
  return map[overlayStrategyType.value] || overlayStrategyType.value
})

// 策略叠加 - 有信号的调仓日
const overlaySignalDays = computed(() => {
  if (!overlayData.value?.daily_signals) return []
  // 按日期倒序：最新交易日置顶
  const days = [...overlayData.value.daily_signals]
    .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
  return days.map(d => {
    const positions = d.positions ? Object.entries(d.positions).map(([code, info]: [string, any]) => ({
      sector_code: code,
      sector_name: info.sector_name || code,
      etf_code: info.etf_code,
      etf_name: info.etf_name,
      weight: info.weight,
      amount: info.amount,
    })) : []
    const positionValue = d.total_position_value || positions.reduce((sum: number, p: any) => sum + (p.amount || 0), 0)
    const cash = d.cash || 0
    return {
      date: d.date,
      // 当日状态（EMPTY/HOLD/REBALANCE）：无信号日据此显示原因，
      // 避免把「空仓观望/持有不动」误认为信号未生成
      status: d.status || ((d.signals || []).length ? 'REBALANCE' : 'HOLD'),
      buySignals: (d.signals || []).filter((s: any) => s.direction === 'BUY'),
      sellSignals: (d.signals || []).filter((s: any) => s.direction === 'SELL'),
      strategy_return: d.strategy_return,
      benchmark_return: d.benchmark_return,
      positions,
      total_position_value: positionValue,
      cash,
      total_asset: d.total_asset != null ? d.total_asset : positionValue + cash,
    }
  })
})

function formatMoney(val: number): string {
  return (val / 10000).toFixed(1)
}

function overlayActionLabel(action: string): string {
  const map: Record<string, string> = {
    ADD: '加仓', REDUCE: '减仓', CLEAR: '清仓',
    STOP_LOSS: '止损', TAKE_PROFIT: '止盈', EMERGENCY_EXIT: '紧急清仓', BEAR_EXIT: '熊市清仓',
    HOLD: '继续持有',
  }
  return map[action] || action
}

function overlayTradeTagType(action: string): 'danger' | 'warning' | 'success' | 'info' {
  const map: Record<string, 'danger' | 'warning' | 'success' | 'info'> = {
    ADD: 'danger', REDUCE: 'warning', CLEAR: 'success',
    STOP_LOSS: 'danger', TAKE_PROFIT: 'warning', EMERGENCY_EXIT: 'danger', BEAR_EXIT: 'danger',
    HOLD: 'info',
  }
  return map[action] || 'info'
}

function overlayTriggerLabel(trigger: string): string {
  const map: Record<string, string> = {
    rebalance: '调仓', stop_loss: '止损', emergency_exit: '紧急退出', bear_exit: '熊市清仓',
  }
  return map[trigger] || trigger
}

function formatOverlayMoney(val: number): string {
  if (val == null) return '-'
  return (val / 10000).toFixed(2) + '万'
}

const overlayRebalanceGroups = computed(() => {
  const changes = overlayData.value?.position_changes
  const snapshots = overlayData.value?.portfolio_snapshots || []
  if (!changes?.length) return []
  const groupMap: Record<string, { date: string; trades: any[]; snapshot: any }> = {}
  for (const item of changes) {
    const d = item.date
    if (!groupMap[d]) {
      const snap = snapshots.find((s: any) => s.date === d)
      groupMap[d] = { date: d, trades: [], snapshot: snap || null }
    }
    groupMap[d].trades.push(item)
  }
  // 调仓日按日期倒序：最近的调仓显示在最前面
  return Object.values(groupMap)
    .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
})

// ============ 日期禁用 ============
function disableDate(date: Date): boolean {
  // 1. 排除周末（周六、周日）
  const day = date.getDay()
  if (day === 0 || day === 6) return true
  
  // 2. 如果有可用日期列表，只允许选择有数据的交易日
  if (availableDates.value.length === 0) return false
  return !availableDates.value.includes(dayjs(date).format('YYYY-MM-DD'))
}

// ============ 按日期回放逻辑 ============
async function loadAvailableDates() {
  try {
    const start = dateRange.value?.[0] || dataAvailability.min_date || undefined
    const end = dateRange.value?.[1] || dataAvailability.max_date || undefined
    const data = await settingsApi.getReplayDates(start, end)
    availableDates.value = data || []
    if (data.length > 0 && !selectedDate.value) {
      selectedDate.value = data[data.length - 1]
      currentDateIndex.value = data.length - 1
    }
  } catch { ElMessage.error('加载日期列表失败') }
}

async function loadDayData() {
  if (!selectedDate.value) { ElMessage.warning('请先选择日期'); return }
  loading.value = true
  try {
    // 设置一个空key让图表强制重建
    const loadingKey = 'loading-' + Date.now()
    dayData.value = { date: loadingKey, sectors: [], count: 0 }
    await new Promise(r => setTimeout(r, 100))
    const newData = await settingsApi.getReplayDayData(selectedDate.value, selectedSector.value || undefined)
    dayData.value = newData
    currentDateIndex.value = availableDates.value.indexOf(selectedDate.value)
  } catch { ElMessage.error('加载数据失败') }
  finally { loading.value = false }
}

function onDateChange(val: string) { if (val) { selectedDate.value = val; loadDayData() } }
function onDateRangeChange() { loadAvailableDates() }
function onSectorFilterChange() { if (selectedDate.value) loadDayData() }

function stepBackward() {
  if (currentDateIndex.value > 0) { currentDateIndex.value--; selectedDate.value = availableDates.value[currentDateIndex.value]; loadDayData() }
}
function stepForward() {
  if (currentDateIndex.value < availableDates.value.length - 1) { currentDateIndex.value++; selectedDate.value = availableDates.value[currentDateIndex.value]; loadDayData() }
}

function toggleAutoPlay() {
  if (autoPlaying.value) { stopAutoPlay() } else {
    if (!selectedDate.value) { ElMessage.warning('请先加载某日数据'); return }
    autoPlaying.value = true; autoPlayStep()
  }
}
function autoPlayStep() {
  if (!autoPlaying.value) return
  if (currentDateIndex.value >= availableDates.value.length - 1) { stopAutoPlay(); ElMessage.info('回放已结束'); return }
  stepForward()
  autoPlayTimer = setTimeout(autoPlayStep, playSpeed.value * 1000)
}
function stopAutoPlay() { autoPlaying.value = false; if (autoPlayTimer) { clearTimeout(autoPlayTimer); autoPlayTimer = null } }

// ============ 按板块回放逻辑 ============
async function loadSectorHistory() {
  if (!selectedSectorForHistory.value) { ElMessage.warning('请先选择板块'); return }
  sectorLoading.value = true
  try {
    const start = sectorDateRange.value?.[0] || dataAvailability.min_date || undefined
    const end = sectorDateRange.value?.[1] || dataAvailability.max_date || undefined
    const data = await settingsApi.getReplaySectorHistory(selectedSectorForHistory.value, start, end)
    // 过滤掉周末（非交易日），后端数据本身应该只有交易日，但前端做双重保障
    sectorHistory.value = data.filter((item: any) => {
      const d = new Date(item.date)
      return d.getDay() !== 0 && d.getDay() !== 6
    })
    if (!sectorHistory.value.length) ElMessage.info('该板块在选定时间段内无数据')
  } catch { ElMessage.error('加载板块历史数据失败') }
  finally { sectorLoading.value = false }
}
function onSectorHistoryChange() { sectorHistory.value = [] }

// ============ 策略叠加回放逻辑 ============
async function loadStrategyOverlay() {
  if (!overlayDateRange.value?.[0] || !overlayDateRange.value?.[1]) {
    ElMessage.warning('请选择时间范围'); return
  }
  overlayLoading.value = true
  
  if (autoOptimize.value) {
    await runAutoOptimization()
    return
  }
  
  replayTaskStore.start('overlay', {
    strategyType: overlayStrategyType.value,
    startDate: overlayDateRange.value[0],
    endDate: overlayDateRange.value[1],
    initialCapital: overlayCapital.value,
  })
  try {
    // 后台任务模式：启动请求立即返回，计算在后端线程池进行。
    // 进度与结果由常驻小卡轮询（不依赖本页面是否挂载），切页/刷新都不会中断。
    await settingsApi.runStrategyOverlay({
      start_date: overlayDateRange.value[0],
      end_date: overlayDateRange.value[1],
      strategy_type: overlayStrategyType.value,
      initial_capital: overlayCapital.value,
    })
    // 页面在场时同步轮询结果，完成后填回明细；离开页面后由小卡接手
    void waitOverlayAndApply()
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '策略回放失败'
    replayTaskStore.fail(detail)
    ElMessage.error(detail ? `策略回放失败：${detail}` : '策略回放失败')
    overlayLoading.value = false
  }
}

// 轮询叠加回测结果并填回页面 + 更新悬浮卡
async function waitOverlayAndApply() {
  for (let i = 0; i < 600; i++) {
    await new Promise(r => setTimeout(r, 1000))
    const r: any = await settingsApi.getOverlayResult().catch(() => null)
    if (!r) continue
    if (r.status === 'running') continue
    overlayLoading.value = false
    if (r.status === 'failed') {
      replayTaskStore.fail(r.error || '策略回放失败')
      ElMessage.error(`策略回放失败：${r.error || '未知错误'}`)
      return
    }
    const data = r.result
    if (!data) return
    overlayData.value = data
    const s = data.summary
    replayTaskStore.finish({
      totalReturn: s?.total_return,
      maxDrawdown: s?.max_drawdown,
      sharpeRatio: s?.sharpe_ratio,
      data,
    })
    ElMessage.success('策略回放完成')
    return
  }
}

async function runAutoOptimization() {
  totalCombinations.value = nTrials.value
  optimizationProgress.value = 0
  overlayLoading.value = true
  abortOptimize.value = false
  bestParams.value = null
  overlayData.value = null

  replayTaskStore.start('optimize', {
    strategyType: overlayStrategyType.value,
    startDate: overlayDateRange.value[0],
    endDate: overlayDateRange.value[1],
    total: nTrials.value,
  })

  try {
    // 触发后台寻优（立即返回），随后轮询进度直至完成
    await settingsApi.runStrategyOptimize({
      start_date: overlayDateRange.value[0],
      end_date: overlayDateRange.value[1],
      strategy_type: overlayStrategyType.value,
      initial_capital: overlayCapital.value,
      n_trials: nTrials.value,
    })

    // 轮询等待寻优完成（后台运行可能远超HTTP超时，因此不走长连接）
    await waitOptimizeAndApply()
  } catch (e: any) {
    if (!abortOptimize.value) {
      const detail = e?.response?.data?.detail || e?.message || '未知错误'
      replayTaskStore.fail(detail)
      ElMessage.error('策略寻优失败: ' + (e?.message || '未知错误'))
    }
  } finally {
    overlayLoading.value = false
  }
}

// 轮询寻优进度直至完成，并取回完整结果填回页面 + 更新悬浮卡。
// 正常启动与刷新后续接共用这一份逻辑。
async function waitOptimizeAndApply() {
  try {
    while (!abortOptimize.value) {
      await new Promise(resolve => setTimeout(resolve, 2000))
      let p: any
      try {
        p = await settingsApi.getOptimizeProgress()
      } catch { continue }
      if (p.total) totalCombinations.value = p.total
      optimizationProgress.value = p.completed
      replayTaskStore.updateProgress(p.completed, p.total)
      if (!p.active) break
    }
    if (abortOptimize.value) return

    // 确保进度显示为 100%
    optimizationProgress.value = totalCombinations.value

    const res: any = await settingsApi.getOptimizeResult()
    const result = res?.result
    if (result && result.best_params && result.best_result) {
      // 训练集 + 样本外拼接后展示，覆盖用户所选的完整区间。
      // 只展示 best_result（训练集）时，样本外整段没有数据，会被误认为「信号不再生成」。
      const oos = result.out_of_sample || null
      // 按日期合并：样本外继承训练集末权益后，切分点两侧连续；
      // 用 Map 去重可防止切分点重合时出现重复点
      const byDate = (a: any[], b: any[]) => {
        const m = new Map<string, any>()
        for (const x of [...(a || []), ...(b || [])]) {
          if (x?.date) m.set(x.date, x)
        }
        return [...m.values()].sort((x, y) =>
          String(x.date).localeCompare(String(y.date)))
      }
      overlayData.value = {
        daily_signals: byDate(result.best_result.daily_signals, oos?.daily_signals),
        nav_curve: byDate(result.best_result.nav_curve, oos?.nav_curve),
        // 全区间汇总优先：顶部指标与拼接后的完整曲线口径一致，
        // 缺失时（无样本外）回退到训练集结果
        summary: result.combined_summary || result.best_result,
        position_changes: byDate(result.best_result.position_changes, oos?.position_changes),
        portfolio_snapshots: byDate(result.best_result.portfolio_snapshots, oos?.portfolio_snapshots),
      }
      bestParams.value = result.best_params
      // 保存完整结果用于结果面板展示，并刷新历史记录（最新置顶）
      optimizeResult.value = result
      await loadOptimizeHistory()

      const totalReturn = (result.best_result.total_return * 100).toFixed(2)
      const maxDrawdown = (result.best_result.max_drawdown * 100).toFixed(2)
      const combos = result.all_results?.length || 0
      replayTaskStore.finish({
        totalReturn: result.best_result.total_return,
        maxDrawdown: result.best_result.max_drawdown,
        sharpeRatio: result.best_result.sharpe_ratio,
        message: `测试${combos}种参数`,
        data: overlayData.value,
      })
      ElMessage.success({
        message: `寻优完成! 测试${combos}种参数, 最优收益=${totalReturn}%, 最大回撤=${maxDrawdown}%`,
        duration: 5000,
      })
    } else {
      replayTaskStore.fail('无有效结果')
      ElMessage.error('寻优失败: 无有效结果')
    }
  } catch (e: any) {
    if (!abortOptimize.value) {
      const detail = e?.response?.data?.detail || e?.message || '未知错误'
      replayTaskStore.fail(detail)
      ElMessage.error('策略寻优失败: ' + (e?.message || '未知错误'))
    }
  } finally {
    overlayLoading.value = false
  }
}

function onModeChange() {
  // 切页签只停止「按日期回放」的自动轮播；回测任务（含寻优轮询）继续在后台跑，
  // 悬浮卡持续显示进度，不再因切换 tab 而中断或清除
  stopAutoPlay()
}

// ============ 资金流向柱状图（按日期）- 双面板布局 ============
/**
 * 提示框定位：ECharts 默认只在容器内翻转，容器被视口裁掉时提示框会直接探出屏幕
 * （实测 390×844 下提示框底部越界 22px）。这里先按「指针右侧、贴指针上方」摆放，
 * 再夹进「容器可见区 ∩ 视口」的矩形里。
 */
function clampTooltipPosition(point: number[], size: any, host: HTMLElement | null) {
  const [w, h] = (size?.contentSize || [0, 0]) as [number, number]
  const box = host?.getBoundingClientRect()
  const originX = box?.left ?? 0
  const originY = box?.top ?? 0
  const vw = window.innerWidth
  const vh = window.innerHeight
  const left = Math.max(originX, 0) + 4
  const right = Math.min(originX + (box?.width ?? vw), vw) - 4
  const top = Math.max(originY, 0) + 4
  const bottom = Math.min(originY + (box?.height ?? vh), vh) - 4
  let vx = originX + point[0] + 12
  if (vx + w > right) vx = originX + point[0] - 12 - w
  // 先放指针下方，下方放不下才翻到上方，两头都放不下就贴边
  let vy = originY + point[1] + 12
  if (vy + h > bottom) vy = originY + point[1] - h - 12
  vx = Math.min(Math.max(vx, left), Math.max(left, right - w))
  vy = Math.min(Math.max(vy, top), Math.max(top, bottom - h))
  return [vx - originX, vy - originY]
}

const flowChartOption = computed(() => {
  if (!dayData.value?.sectors?.length) return {}
  const isDark = themeStore.mode === 'dark'
  const gridColor = isDark ? '#2a2d38' : '#ebeef5'
  const textColor = isDark ? '#9da1b0' : '#5a5f6e'
  const sorted = [...dayData.value.sectors].sort((a, b) => b.index_change_pct - a.index_change_pct)
  const sectorNames = sorted.map(s => s.sector_name)
  const changes = sorted.map(s => s.index_change_pct)
  const mainFlow = sorted.map(s => +(s.main_net_inflow / 1e8).toFixed(2))
  const northFlow = sorted.map(s => +(s.north_net_inflow / 1e8).toFixed(2))
  return {
    notMerge: true,
    // 同 7.5.4：带 dataZoom 的图表一律关掉更新动画，拖动/缩放才能即时重绘
    animationDurationUpdate: 0,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      position: (point: number[], _params: any, _dom: any, _rect: any, size: any) =>
        clampTooltipPosition(point, size, document.querySelector('.flow-chart') as HTMLElement | null),
      formatter: (params: any) => {
        const idx = params[0]?.dataIndex
        if (idx === undefined) return ''
        const s = sorted[idx]
        let html = `<b>${s.sector_name}</b><br/>`
        html += `涨跌幅: ${s.index_change_pct >= 0 ? '+' : ''}${s.index_change_pct.toFixed(2)}%<br/>`
        html += `主力净流入: ${(s.main_net_inflow / 1e8).toFixed(2)}亿<br/>`
        html += `北向净流入: ${(s.north_net_inflow / 1e8).toFixed(2)}亿（已停用）`
        return html
      }
    },
    // 规则7.5.3：移动端图例顶部单行9px最多2项（北向已停用不展示）
    legend: {
      data: bp.isMobile.value ? ['涨跌幅(%)', '主力净流入(亿)'] : ['涨跌幅(%)', '主力净流入(亿)', '北向净流入(亿)(已停用)'],
      selectedMode: 'multiple', top: 2, left: 'center', itemWidth: 12, itemHeight: 8,
      textStyle: { color: textColor, fontSize: bp.isMobile.value ? 9 : 12 },
    },
    grid: bp.isMobile.value
      ? [
          { left: 46, right: 12, top: 28, height: '38%' },
          { left: 46, right: 12, top: '62%', height: '22%' },
        ]
      : [
          { left: 70, right: 50, top: 35, height: '40%' },
          { left: 70, right: 50, top: '56%', height: '26%' },
        ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 0, end: 100, bottom: 4, height: 18, textStyle: { color: textColor } },
    ],
    xAxis: [
      { type: 'category', data: sectorNames, gridIndex: 0, axisLabel: { show: false }, position: 'top' },
      { type: 'category', data: sectorNames, gridIndex: 1, axisLabel: { rotate: 45, fontSize: 9, color: textColor, interval: Math.max(bp.labelInterval(sectorNames.length), 2) }, position: 'bottom' },
    ],
    // 规则7.5.3：移动端隐藏轴名称（靠图例颜色区分），避免名称压在图上
    yAxis: [
      { type: 'value', name: bp.isMobile.value ? '' : '涨跌幅(%)', position: 'left', gridIndex: 0, nameTextStyle: { color: textColor, fontSize: 10 }, axisLine: { show: true, lineStyle: { color: isDark ? '#7b93f5' : '#409eff' } }, axisLabel: { formatter: '{value}%', fontSize: 9, color: isDark ? '#646878' : '#9499a6' }, splitLine: { lineStyle: { color: gridColor } } },
      { type: 'value', name: bp.isMobile.value ? '' : '主力(亿)', position: 'left', gridIndex: 1, offset: 0, nameTextStyle: { color: textColor, fontSize: 10 }, axisLine: { show: true, lineStyle: { color: isDark ? '#f06060' : '#f56c6c' } }, axisLabel: { formatter: '{value}', margin: 6, fontSize: 9, color: isDark ? '#646878' : '#9499a6' }, splitLine: { lineStyle: { color: gridColor } } },
      ...(bp.isMobile.value ? [] : [{ type: 'value', name: '北向(亿)(停用)', position: 'right', gridIndex: 1, axisLine: { show: true, lineStyle: { color: '#909399' } }, axisLabel: { formatter: '{value}', margin: 8, color: isDark ? '#646878' : '#9499a6' }, splitLine: { show: false } }]),
    ],
    series: [
      { name: '涨跌幅(%)', type: 'bar', xAxisIndex: 0, yAxisIndex: 0, data: changes, itemStyle: { color: (p: any) => p.data >= 0 ? '#f56c6c' : '#67c23a' }, barMaxWidth: 24 },
      { name: '主力净流入(亿)', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: mainFlow, itemStyle: { color: '#f56c6c' }, barMaxWidth: 16 },
      ...(bp.isMobile.value ? [] : [{ name: '北向净流入(亿)(已停用)', type: 'bar', xAxisIndex: 1, yAxisIndex: 2, data: northFlow, itemStyle: { color: '#909399', opacity: 0.5 }, barMaxWidth: 16 }]),
    ],
  }
})

// 雪球式手势：移动端单指平移自己接管（ECharts inside 在移动端拖动跟手差），双指捏合仍交给 inside；长按自绘十字线
const sectorChartRef = ref<any>(null)
const CROSS_HOLD_MS = 280
const CROSS_MOVE_EPS = 8 // 超过该位移即视为滑动，取消长按
let crossTimer: ReturnType<typeof setTimeout> | null = null
let pressStart: { x: number; y: number; id: number } | null = null
let crossActive = false
let crosshairLayer: HTMLElement | null = null
// 自定义平移：按下时锁定 dataZoom 窗口，move 时按 dx 像素直接换算 start/end
let panBase: { x: number; start: number; end: number; id: number } | null = null

function echartsInst() {
  // vue-echarts 把 _echarts_instance_ 挂在内部 wrapper 上，不是根 div
  const dom = document.querySelector('.sector-history-chart [_echarts_instance_]') as HTMLElement | null
  const fromDom = dom ? getInstanceByDom(dom) : null
  if (fromDom) return fromDom
  const c = sectorChartRef.value
  return c?.chart || c?.getEchartsInstance?.() || c?.getChart?.() || null
}

/** 移动端自绘十字线：竖虚线 + 顶部横条，脱离 ECharts axisPointer，避免与平移争用指针状态 */
function showCrosshair(clientX: number, clientY: number) {
  const inst = echartsInst()
  if (!inst) return
  const host = document.querySelector('.sector-history-chart') as HTMLElement | null
  if (!host) return
  const hostRect = host.getBoundingClientRect()
  const rect = inst.getDom().getBoundingClientRect()
  const pt = inst.convertFromPixel({ gridIndex: 0 }, [clientX - rect.left, clientY - rect.top]) as number[]
  if (!pt) return
  const bars = aggregatedHistory.value
  const idx = Math.max(0, Math.min(bars.length - 1, Math.round(pt[0])))

  // 页面可能有多个同名容器，用模块级引用避免 querySelector 取错导致松手清不掉
  if (!crosshairLayer || !crosshairLayer.isConnected) {
    crosshairLayer = document.createElement('div')
    crosshairLayer.className = 'kline-crosshair'
    crosshairLayer.innerHTML = '<span class="kline-crosshair-line"></span><span class="kline-crosshair-tip"></span>'
    // 动态节点需带 scoped 属性，否则 scoped CSS 不匹配（position 不生效）
    const scope = host.getAttributeNames().find(n => n.startsWith('data-v-'))
    if (scope) {
      const value = host.getAttribute(scope)!
      crosshairLayer.setAttribute(scope, value)
      crosshairLayer.querySelectorAll('*').forEach(el => el.setAttribute(scope, value))
    }
    host.appendChild(crosshairLayer)
  }
  const layer = crosshairLayer
  const line = layer.querySelector('.kline-crosshair-line') as HTMLElement
  const tip = layer.querySelector('.kline-crosshair-tip') as HTMLElement

  // 竖线钉在触点 x（相对 host），横条固定在图顶
  const x = Math.max(0, Math.min(hostRect.width, clientX - hostRect.left))
  line.style.left = `${x}px`
  line.style.display = 'block'

  const s = bars[idx]
  const candleData = (inst.getOption() as any).series?.[0]?.data?.[idx]
  // candlestick data 为 4 元素 [open, close, low, high]；折线模式为收盘价数字
  const [open, close, low, high] = Array.isArray(candleData)
    ? candleData
    : [candleData, candleData, candleData, candleData]
  const pct = s?.index_change_pct || 0
  const color = pct >= 0 ? '#ef232a' : '#14b143'
  tip.innerHTML = `<span class="kh-date">${(s?.date || '').slice(5)}</span> 开 ${Math.round(open)} 高 ${Math.round(high)} 低 ${Math.round(low)} 收 ${Math.round(close)} <span style="color:${color}">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</span> 主力 ${((s?.main_net_inflow || 0) / 1e8).toFixed(2)}亿`
  tip.style.display = 'inline-block'
}

function cancelLongPress() {
  if (crossTimer) { clearTimeout(crossTimer); crossTimer = null }
}

function clearCross() {
  cancelLongPress()
  const inst = echartsInst()
  if (inst) {
    // hideTip 只关横条，axisPointer 竖虚线属独立组件，必须发 leave 才会移除
    inst.dispatchAction({ type: 'hideTip' })
    inst.dispatchAction({ type: 'updateAxisPointer', currTrigger: 'leave' })
  }
  // 隐藏自绘十字线层（竖线 + 横条），用模块级引用避免 querySelector 取错容器
  if (crosshairLayer) {
    const line = crosshairLayer.querySelector<HTMLElement>('.kline-crosshair-line')
    const tip = crosshairLayer.querySelector<HTMLElement>('.kline-crosshair-tip')
    if (line) line.style.display = 'none'
    if (tip) tip.style.display = 'none'
  }
  crossActive = false
  pressStart = null
}

function bindKlineGestures() {
  const host = document.querySelector('.sector-history-chart') as HTMLElement | null
  if (!host || (host as any).__klineGestureBound) return
  ;(host as any).__klineGestureBound = true

  // 捕获阶段监听：移动端自己接管单指平移，长按切十字线
  host.addEventListener('pointerdown', (e) => {
    if (!bp.isMobile.value || e.pointerType === 'mouse') return
    // 底部滑块区（slider bottom 5 + height 18）让给 ECharts slider：自接管平移每帧
    // dispatch 同宽度窗口，会把拖手柄覆盖成整体平移，手柄再也拖不窄（见 docs 7.5.4）
    if (e.clientY > host.getBoundingClientRect().bottom - 26) return
    clearCross() // 新触摸先清掉上一次残留的十字线
    if (!e.isPrimary) { panBase = null; return } // 第二根手指：捏合缩放优先
    pressStart = { x: e.clientX, y: e.clientY, id: e.pointerId }
    // 锁定当前 dataZoom 窗口作为平移基准
    const dz = (echartsInst()?.getOption() as any)?.dataZoom?.find((d: any) => d.type === 'inside')
    panBase = dz ? { x: e.clientX, start: Number(dz.start) || 0, end: Number(dz.end) ?? 100, id: e.pointerId } : null
    crossTimer = setTimeout(() => {
      crossTimer = null
      if (!pressStart) return
      crossActive = true
      panBase = null // 进入十字线模式，停止平移
      showCrosshair(pressStart.x, pressStart.y)
    }, CROSS_HOLD_MS)
  }, true)

  host.addEventListener('pointermove', (e) => {
    if (!bp.isMobile.value || !pressStart || e.pointerId !== pressStart.id) return
    const dist = Math.hypot(e.clientX - pressStart.x, e.clientY - pressStart.y)
    if (crossActive) {
      // 十字线模式：拦截 move，只让自绘十字线跟随，不平移
      e.stopPropagation()
      if (dist > CROSS_MOVE_EPS) showCrosshair(e.clientX, e.clientY)
      return
    }
    if (dist <= CROSS_MOVE_EPS) return
    cancelLongPress() // 确认为滑动，取消长按
    if (!panBase) return
    // 拖拽内容语义：右滑(dx>0)露出左侧更早的数据 → start 减小；左滑(dx<0)看更晚数据 → start 增大。
    // dx 占图宽比例 × 当前窗口跨度 = 窗口应移动的百分点
    const width = host.getBoundingClientRect().width || 348
    const span = panBase.end - panBase.start
    const deltaPct = ((e.clientX - panBase.x) / width) * span
    let start = panBase.start - deltaPct
    let end = panBase.end - deltaPct
    if (start < 0) { start = 0; end = span }
    if (end > 100) { end = 100; start = 100 - span }
    // 不指定 dataZoomIndex，同步 inside + slider 两个组件，避免窗口不一致造成闪烁/不绘制
    echartsInst()?.dispatchAction({ type: 'dataZoom', start, end })
  }, true)

  // 松手/取消：zrender 可能捕获指针导致 host 收不到，document 捕获阶段兜底
  if (!(document as any).__klineGestureEndBound) {
    ;(document as any).__klineGestureEndBound = true
    document.addEventListener('pointerup', onGestureEnd, true)
    document.addEventListener('pointercancel', onGestureEnd, true)
  }
}

function onGestureEnd() {
  if (!bp.isMobile.value) return
  // 移动端任何抬手都直接隐藏十字线 DOM，不依赖模块变量状态（HMR/捕获差异下状态可能不同步）
  document.querySelectorAll('.kline-crosshair-line, .kline-crosshair-tip').forEach((el) => {
    (el as HTMLElement).style.display = 'none'
  })
  panBase = null
  if (crossActive || pressStart) clearCross()
}

function onKlineDataZoom(e?: any) {
  const total = aggregatedHistory.value.length
  if (!total) return
  // 优先用事件参数（ECharts 直接给出的实际窗口），避免 getOption 在拖动路径下返回旧值
  const payload = e?.batch?.[0] || e
  let start: number
  let end: number
  if (payload && Number.isFinite(payload.start) && Number.isFinite(payload.end)) {
    start = payload.start
    end = payload.end
  } else {
    const opt = echartsInst()?.getOption() as any
    const dz = (opt?.dataZoom || []).find((d: any) => d.type === 'inside') || opt?.dataZoom?.[0]
    if (!dz) return
    start = Number(dz.start) || 0
    end = Number(dz.end) ?? 100
  }
  klineStart = start
  klineEnd = end
  klineSpan.value = Math.max(1, Math.round(((end - start) / 100) * total))
}

watch(klinePeriod, () => {
  const total = aggregatedHistory.value.length
  klineSpan.value = Math.min(60, total)
  klineStart = total ? Math.max(0, (1 - Math.min(60, total) / total) * 100) : 100
  klineEnd = 100
})
watch(() => sectorHistory.value.length, async (n) => {
  if (n) {
    klineSpan.value = Math.min(60, n)
    klineStart = Math.max(0, (1 - Math.min(60, n) / n) * 100)
    klineEnd = 100
  }
  await nextTick()
  bindKlineGestures()
})
onMounted(async () => { await nextTick(); bindKlineGestures() })
onUpdated(() => bindKlineGestures())
onUnmounted(() => {
  if (crossTimer) clearTimeout(crossTimer)
})

// ============ 板块K线图 + 资金流（按板块）- 双面板布局 ============
const sectorHistoryChartOption = computed(() => {
  if (!sectorHistory.value.length) return {}
  const isDark = themeStore.mode === 'dark'
  const gridColor = isDark ? '#2a2d38' : '#eee'
  const textColor = isDark ? '#9da1b0' : '#5a5f6e'
  const bars = aggregatedHistory.value
  const dates = bars.map(s => s.date)
  const changes = bars.map(s => s.index_change_pct)

  // 构建K线数据 [open, close, low, high]
  const candleData: number[][] = []
  let prevClose = bars[0]?.index_close ?? 3000
  const hasRealOHLC = bars.some(s => s.open != null && s.high != null && s.low != null)
  // 真实 OHLC 要求四个价格都 > 0：收盘后若当日 K 线还没采到，接口只给 open/high/low = 0、无 close，
  // 直接画会得到一根从 0 拉起的超长蜡烛，故这一根退回按涨跌幅合成
  const validOhlc = (s: any) => [s.open, s.close, s.high, s.low].every(v => Number.isFinite(Number(v)) && Number(v) > 0)

  for (const s of bars) {
    if (hasRealOHLC && validOhlc(s)) {
      candleData.push([+s.open.toFixed(2), +s.close.toFixed(2), +s.low.toFixed(2), +s.high.toFixed(2)])
    } else {
      const close = s.index_close || (prevClose * (1 + (s.index_change_pct || 0) / 100))
      const pct = (s.index_change_pct || 0) / 100
      const open = prevClose
      const range = Math.abs(pct) * close * 0.6 + close * 0.003
      const high = Math.max(open, close) + range * 0.3
      const low = Math.min(open, close) - range * 0.3
      candleData.push([+open.toFixed(2), +close.toFixed(2), +low.toFixed(2), +high.toFixed(2)])
    }
    prevClose = s.close || s.index_close || prevClose
  }

  // 四条均线按当前周期重算
  const closes = candleData.map(d => d[1])
  const maValues: Record<MaKey, (number | null)[]> = { ma5: [], ma10: [], ma20: [], ma60: [] }
  for (const m of maSeries) {
    maValues[m.key] = closes.map((_, i) => i < m.period - 1
      ? null
      : +(closes.slice(i - m.period + 1, i + 1).reduce((a, b) => a + b, 0) / m.period).toFixed(2))
  }

  // 资金流数据
  const mainFlow = bars.map(s => +(s.main_net_inflow / 1e8).toFixed(2))
  const northFlow = bars.map(s => +(s.north_net_inflow / 1e8).toFixed(2))

  return {
    // 拖动/缩放走 dispatchAction 每帧更新，若保留更新动画（默认 500ms），
    // 每帧都会重启一次过渡动画并互相排队，实测松手后画面仍要追 0.5-1s 才到位，
    // 表现为「K 线过一会儿才过来且过来后才重绘」。更新动画置 0，首帧淡入动画保留。
    animationDurationUpdate: 0,
    // 手机端提示框固定在图顶单行横条，不随触点浮在 K 线上
    tooltip: bp.isMobile.value
      ? {
          trigger: 'axis',
          // 移动端由长按/滑动手势 dispatchAction 控制，避免单指平移时十字线乱跳
          triggerOn: 'none',
          confine: true,
          transitionDuration: 0, // 松手立即移除提示框 DOM，不留淡出残影
          axisPointer: { type: 'line', lineStyle: { color: '#637EE8', width: 1, type: 'dashed' } },
          position: (point: number[], _p: any, _dom: any, _rect: any, size: any) => {
            const w = size.contentSize[0] as number
            // 图例占顶部 0-14px，横条落在 18-42px；K 线 grid 从 45px 开始
            return [Math.max(4, Math.min(point[0] - w / 2, size.viewSize[0] - w - 4)), 18]
          },
          backgroundColor: isDark ? 'rgba(30,32,40,0.98)' : 'rgba(255,255,255,0.98)',
          borderColor: isDark ? '#3f3f46' : '#e4e4e7',
          borderWidth: 1,
          padding: [3, 8],
          textStyle: { color: isDark ? '#e4e4e7' : '#27272a', fontSize: 11 },
          extraCssText: 'border-radius:4px;box-shadow:none;white-space:nowrap;line-height:16px;',
          formatter: (params: any) => {
            const list = Array.isArray(params) ? params : [params]
            const idx = list[0]?.dataIndex
            if (idx === undefined) return ''
            const s = bars[idx]
            const candle = list.find((p: any) => p.seriesName === 'K线')
            const d = candle?.data
            if (d == null) return ''
            // 折线模式下 data 是收盘价数字，不是 [index, open, close, low, high]
            const ohlc = Array.isArray(d) ? d : [0, d, d, d, d]
            const [, open, close, low, high] = ohlc
            const pct = s.index_change_pct || 0
            const color = pct >= 0 ? '#ef232a' : '#14b143'
            return `<span style="color:${textColor}">${s.date.slice(5)}</span> 开 ${Math.round(open)} 高 ${Math.round(high)} 低 ${Math.round(low)} 收 ${Math.round(close)} <span style="color:${color}">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</span> 主力 ${(s.main_net_inflow / 1e8).toFixed(2)}亿`
          },
        }
      : {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          formatter: (params: any) => {
            const idx = params[0]?.dataIndex
            if (idx === undefined) return ''
            const s = bars[idx]
            const candle = params.find((p: any) => p.seriesName === 'K线')
            let html = `<b>${s.date}</b><br/>`
            if (candle && candle.data != null) {
              const d = Array.isArray(candle.data) ? candle.data : [0, candle.data, candle.data, candle.data, candle.data]
              html += `开: ${d[1]} 收: ${d[2]} 低: ${d[3]} 高: ${d[4]}<br/>`
            }
            html += `涨跌幅: ${s.index_change_pct?.toFixed(2)}%<br/>`
            html += `主力净流入: ${(s.main_net_inflow / 1e8).toFixed(2)}亿<br/>`
            html += `北向净流入: ${(s.north_net_inflow / 1e8).toFixed(2)}亿（已停用）`
            return html
          },
        },
    // 图例与周期切换放到图表外的 .kline-toolbar，避免与 K 线区争夺顶部空间
    legend: { show: false },
    // 上下双面板：上方K线占70%，下方资金流占30%
    grid: bp.isMobile.value
      ? [
          { left: 4, right: 4, top: 45, height: '52%' },  // K线主图：刻度内置后铺满视口
          { left: 4, right: 4, top: '72%', height: '20%' }, // 资金流副图
        ]
      : [
          { left: 70, right: 20, top: 45, height: '52%' },  // K线主图
          { left: 70, right: 20, top: '72%', height: '20%' }, // 资金流副图
        ],
    xAxis: [
      { type: 'category', data: dates, axisLabel: { show: false }, axisTick: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { rotate: bp.isMobile.value ? 90 : 30, fontSize: bp.isMobile.value ? 9 : 10, color: textColor, interval: bp.labelInterval(dates.length) } },
    ],
    yAxis: [
      {
        type: 'value', name: bp.isMobile.value ? '' : '指数', scale: true,
        nameTextStyle: { color: textColor },
        axisLabel: bp.isMobile.value
          ? { color: '#8a94a6', fontSize: 9, inside: true, margin: 4 }
          : { color: isDark ? '#646878' : '#9499a6' },
        axisLine: bp.isMobile.value ? { show: false } : undefined,
        axisTick: bp.isMobile.value ? { show: false } : undefined,
        splitLine: { lineStyle: { color: gridColor } },
      },
      {
        type: 'value', name: bp.isMobile.value ? '' : '亿元', gridIndex: 1,
        nameTextStyle: { color: textColor },
        axisLabel: bp.isMobile.value
          ? { color: '#8a94a6', fontSize: 9, inside: true, margin: 4 }
          : { color: isDark ? '#646878' : '#9499a6' },
        axisLine: bp.isMobile.value ? { show: false } : undefined,
        axisTick: bp.isMobile.value ? { show: false } : undefined,
        splitLine: { lineStyle: { color: gridColor } },
      },
    ],
    dataZoom: [
      {
        type: 'inside', xAxisIndex: [0, 1],
        start: klineStart, end: klineEnd,
        // 单指平移 + 双指捏合缩放交给 ECharts inside；长按十字线时临时禁用
        zoomOnMouseWheel: false,
        moveOnMouseWheel: false,
        moveOnMouseMove: !bp.isMobile.value, // 移动端由手势代码自己接管平移，避免 ECharts 内置拖动跟手差
        preventDefaultMouseMove: false,
        minValueSpan: Math.min(MIN_KLINE_BARS, dates.length),
      },
      {
        type: 'slider', xAxisIndex: [0, 1], bottom: 5, height: 18,
        start: klineStart, end: klineEnd,
        minValueSpan: Math.min(MIN_KLINE_BARS, dates.length),
        textStyle: { color: textColor },
      },
    ],
    series: [
      // === 主图：K 线过密时切折线并隐藏均线 ===
      asLine.value
        ? {
            name: 'K线', type: 'line', data: closes, symbol: 'none',
            lineStyle: { width: 1.5, color: '#637EE8' }, itemStyle: { color: '#637EE8' },
          }
        : {
            name: 'K线', type: 'candlestick', data: candleData,
            itemStyle: { color: '#ef232a', color0: '#14b143', borderColor: '#ef232a', borderColor0: '#14b143' },
          },
      ...(asLine.value ? [] : maSeries.filter(m => maVisible.value[m.key]).map(m => ({
        name: m.key.toUpperCase(), type: 'line', data: maValues[m.key], symbol: 'none',
        lineStyle: { width: 1, color: m.color }, itemStyle: { color: m.color },
      }))),
      // === 副图：资金流柱状 ===
      {
        name: '主力净流入(亿)', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: mainFlow,
        itemStyle: { color: (p: any) => p.data >= 0 ? 'rgba(245,108,108,0.7)' : 'rgba(103,194,58,0.7)' },
        barMaxWidth: 12,
      },
      {
        name: '北向净流入(亿)(已停用)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: northFlow,
        smooth: true, symbol: 'none',
        lineStyle: { width: 1.5, color: '#909399', opacity: 0.5 }, itemStyle: { color: '#909399', opacity: 0.5 },
      },
    ],
  }
})

// ============ 策略叠加净值曲线 + 买卖点标记 ============
// 净值曲线的可视窗口（百分比）：买卖点标记按窗口内的像素密度稀释，放大后自动变密
const overlayZoom = ref<[number, number]>([0, 100])
const overlayChartRef = ref<any>(null)
let overlayZoomTimer: ReturnType<typeof setTimeout> | null = null
// 拖动滑块会连续触发 datazoom，节流后再重算标记，避免每帧 setOption
function onOverlayZoom(e: any) {
  const payload = Array.isArray(e?.batch) && e.batch.length ? e.batch[0] : e
  const start = Number(payload?.start)
  const end = Number(payload?.end)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return
  if (overlayZoomTimer) clearTimeout(overlayZoomTimer)
  overlayZoomTimer = setTimeout(() => { overlayZoom.value = [start, end] }, 160)
}
/** 绘图区可用宽度（px）：vue-echarts 根节点优先，兜底取容器或视口宽度 */
function overlayPlotWidth() {
  const el = overlayChartRef.value?.$el as HTMLElement | undefined
  if (el?.clientWidth) return el.clientWidth
  const dom = document.querySelector('.overlay-chart') as HTMLElement | null
  return dom?.clientWidth || bp.width.value
}

const overlayChartOption = computed(() => {
  if (!overlayData.value?.nav_curve?.length) return {}
  const isDark = themeStore.mode === 'dark'
  const gridColor = isDark ? '#2a2d38' : '#ebeef5'
  const textColor = isDark ? '#9da1b0' : '#5a5f6e'
  const curve = overlayData.value.nav_curve
  const signals = overlayData.value.daily_signals

  // 曲线极值统计：最大回撤区间（前高→后低）与净值高点，仅用于标注，不改动原始数据
  const navs: number[] = curve.map((p: any) => Number(p.nav) || 0)
  const baseNav = navs[0] || 1
  let runPeak = navs[0], runPeakIdx = 0
  let ddPeakIdx = 0, ddTroughIdx = 0, ddMax = 0
  let highIdx = 0
  for (let i = 0; i < navs.length; i++) {
    if (navs[i] > runPeak) { runPeak = navs[i]; runPeakIdx = i }
    const dd = runPeak > 0 ? (runPeak - navs[i]) / runPeak : 0
    if (dd > ddMax) { ddMax = dd; ddPeakIdx = runPeakIdx; ddTroughIdx = i }
    if (navs[i] > navs[highIdx]) highIdx = i
  }
  const navRange = Math.max(...navs) - Math.min(...navs)
  const ddCenter = navs.length > 1 ? (ddPeakIdx + ddTroughIdx) / 2 / (navs.length - 1) : 0.5
  const lastNav = navs[navs.length - 1]
  const strategyReturn = baseNav > 0 ? (lastNav / baseNav - 1) * 100 : 0
  const benchLast = Number(curve[curve.length - 1]?.benchmark) || 0
  const benchBase = Number(curve[0]?.benchmark) || 1
  const benchmarkReturn = benchBase > 0 ? (benchLast / benchBase - 1) * 100 : 0
  const excessReturn = strategyReturn - benchmarkReturn
  // 纵轴刻度：净值区间窄时保留小数，宽时取整，统一收敛到「万」
  const navToWan = (v: number) => {
    const w = v / 10000
    if (navRange / 10000 >= 10) return w.toFixed(0) + '万'
    return w.toFixed(2).replace(/\.?0+$/, '') + '万'
  }

  // 买卖点标记：先按「日期 + 方向」聚合（同一天多个板块只画一个点，具体板块在 tooltip 里），
  // 再按当前可视窗口的像素密度稀释，避免长区间把标记糊成一团
  const dateIndexMap: Record<string, number> = {}
  curve.forEach((p: any, i: number) => { dateIndexMap[p.date] = i })
  const buyIdxSet = new Set<number>()
  const sellIdxSet = new Set<number>()
  for (const day of signals) {
    if (!day.signals || day.signals.length === 0) continue
    const idx = dateIndexMap[day.date]
    if (idx === undefined) continue
    for (const sig of day.signals) {
      if (sig.direction === 'BUY') buyIdxSet.add(idx)
      else sellIdxSet.add(idx)
    }
  }
  const totalLen = curve.length
  const [zoomStart, zoomEnd] = overlayZoom.value
  const visFrom = Math.max(0, Math.floor((totalLen - 1) * zoomStart / 100) - 1)
  const visTo = Math.min(totalLen - 1, Math.ceil((totalLen - 1) * zoomEnd / 100) + 1)
  const visCount = Math.max(1, visTo - visFrom + 1)
  // 标记最小横向间距：移动端 20px、桌面 14px，与标记尺寸匹配
  // 容器宽度要扣掉纵轴标签与左右留白，才是曲线真正可用的像素宽度
  const minGapPx = bp.isMobile.value ? 20 : 14
  const plotWidth = Math.max(120, overlayPlotWidth() - (bp.isMobile.value ? 48 : 64))
  const minGapIdx = Math.max(1, Math.ceil(minGapPx / (plotWidth / visCount)))
  const thinMarks = (set: Set<number>) => {
    const idxs = [...set].filter(i => i >= visFrom && i <= visTo).sort((a, b) => a - b)
    if (idxs.length <= 1) return idxs
    const kept = [idxs[0]]
    for (let k = 1; k < idxs.length; k++) {
      if (idxs[k] - kept[kept.length - 1] >= minGapIdx) kept.push(idxs[k])
    }
    // 可视窗口最右侧的信号必须保留，否则缩放后右端看起来没有信号
    const last = idxs[idxs.length - 1]
    if (kept[kept.length - 1] !== last) {
      if (kept.length === 1) kept.push(last)
      else kept[kept.length - 1] = last
    }
    return kept
  }
  const buyPoints = thinMarks(buyIdxSet).map(i => [i, curve[i].nav])
  const sellPoints = thinMarks(sellIdxSet).map(i => [i, curve[i].nav])

  const strategyColor = overlayStrategyType.value === 'AGGRESSIVE' ? '#f56c6c' : overlayStrategyType.value === 'CONSERVATIVE' ? '#67c23a' : '#5f72e8'
  const benchmarkColor = isDark ? '#8b90a0' : '#9aa0ad'
  const titleColor = isDark ? '#e6e8ee' : '#2f3441'
  const axisLabelColor = isDark ? '#7d8291' : '#8a94a6'
  const axisLineColor = isDark ? '#333744' : '#e2e6ef'
  // 十六进制色转 rgba，用于面积渐变与标注淡色
  const alpha = (hex: string, a: number) => {
    const n = parseInt(hex.slice(1), 16)
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
  }
  const mobile = bp.isMobile.value
  const dates = curve.map((p: any) => p.date)

  return {
    // 同 7.5.4：带 dataZoom 的图表一律关掉更新动画，拖动/缩放才能即时重绘
    animationDurationUpdate: 0,
    title: {
      text: '净值走势',
      subtext: mobile
        ? ''
        : `区间收益 ${strategyReturn >= 0 ? '+' : ''}${strategyReturn.toFixed(2)}%　超额 ${excessReturn >= 0 ? '+' : ''}${excessReturn.toFixed(2)}%`,
      left: 4, top: 2,
      itemGap: 4,
      textStyle: { fontSize: mobile ? 11 : 13, fontWeight: 600, color: titleColor },
      subtextStyle: {
        fontSize: 11,
        color: excessReturn >= 0 ? (isDark ? '#e0a0a0' : '#c45656') : (isDark ? '#8fbf8f' : '#4f9a4f'),
      },
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: isDark ? 'rgba(24,26,33,0.94)' : 'rgba(255,255,255,0.97)',
      borderColor: axisLineColor,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: isDark ? '#dfe2ea' : '#2f3441', fontSize: mobile ? 11 : 12 },
      axisPointer: {
        type: 'cross',
        crossStyle: { color: textColor, type: 'dashed' },
        lineStyle: { color: textColor, type: 'dashed' },
        label: { backgroundColor: isDark ? '#3a3f4d' : '#5a5f6e', fontSize: 10 },
      },
      formatter: (params: any) => {
        // 散点系列的 dataIndex 是散点数组下标，必须取主线系列的下标
        const item = (Array.isArray(params) ? params : [params]).find((it: any) => it?.seriesName === '策略净值')
        const idx = item?.dataIndex
        if (idx === undefined || !curve[idx]) return ''
        const point = curve[idx]
        const daySig = signals.find((s: any) => s.date === point.date)
        const dayReturn = baseNav > 0 ? (point.nav / baseNav - 1) * 100 : 0
        let html = `<b>${point.date}</b><br/>`
        html += `策略净值: ${(point.nav / 10000).toFixed(2)}万（${dayReturn >= 0 ? '+' : ''}${dayReturn.toFixed(2)}%）<br/>`
        html += `基准净值: ${(point.benchmark / 10000).toFixed(2)}万<br/>`
        if (point.stop_loss) html += `<span style="color:#e6a23c">止损中</span><br/>`
        if (daySig?.signals?.length) {
          const buySigs = daySig.signals.filter((s: any) => s.direction === 'BUY')
          const sellSigs = daySig.signals.filter((s: any) => s.direction === 'SELL')
          if (buySigs.length) {
            html += `<span style="color:#f56c6c; font-weight:bold">买入: ${buySigs.map((s: any) => s.sector_name).join(', ')}</span><br/>`
          }
          if (sellSigs.length) {
            html += `<span style="color:#67c23a; font-weight:bold">卖出: ${sellSigs.map((s: any) => s.sector_name).join(', ')}</span><br/>`
          }
        }
        return html
      },
    },
    // 规则7.5.3：移动端图例顶部单行、字号 10（文档下限），最多 4 项
    legend: mobile
      ? {
          data: ['策略净值', '基准净值', '买入', '卖出'],
          top: 20, left: 'center', icon: 'roundRect',
          itemWidth: 12, itemHeight: 7, itemGap: 10,
          textStyle: { color: textColor, fontSize: 10 },
        }
      : {
          data: ['策略净值', '基准净值', '买入', '卖出'],
          top: 5, right: 8, icon: 'roundRect',
          itemWidth: 14, itemHeight: 8, itemGap: 16,
          textStyle: { color: textColor, fontSize: 12 },
        },
    // containLabel 自动按轴标签宽度让出留白；移动端不写轴名，省一列宽度
    grid: mobile
      ? { left: 6, right: 10, top: 42, bottom: 34, containLabel: true }
      : { left: 10, right: 24, top: 52, bottom: 36, containLabel: true },
    dataZoom: mobile
      ? [
          { type: 'inside' },
          {
            type: 'slider', height: 14, bottom: 6, left: 6, right: 10,
            showDetail: false, brushSelect: false,
            borderColor: 'transparent', fillerColor: alpha(strategyColor, 0.12),
            handleSize: '90%', handleStyle: { color: axisLineColor, borderColor: axisLineColor },
            dataBackground: { lineStyle: { color: axisLineColor }, areaStyle: { color: axisLineColor, opacity: 0.25 } },
            textStyle: { color: textColor, fontSize: 10 },
          },
        ]
      : [
          { type: 'inside' },
          {
            type: 'slider', height: 16, bottom: 8, left: 10, right: 24,
            brushSelect: false,
            borderColor: 'transparent', fillerColor: alpha(strategyColor, 0.12),
            handleSize: '80%', handleStyle: { color: axisLineColor, borderColor: axisLineColor },
            dataBackground: { lineStyle: { color: axisLineColor }, areaStyle: { color: axisLineColor, opacity: 0.25 } },
            textStyle: { color: textColor, fontSize: 10 },
          },
        ],
    xAxis: {
      type: 'category', data: dates,
      // 留半格边界，首尾买卖点标记不会被绘图区边缘裁掉
      boundaryGap: true,
      axisLine: { lineStyle: { color: axisLineColor } },
      axisTick: { show: false },
      axisLabel: {
        // 只显示月-日，完整日期在 tooltip 里，避免 10 字符标签挤爆窄屏
        formatter: (v: string) => v.slice(5),
        fontSize: 10, color: textColor, margin: 8,
        hideOverlap: true, interval: bp.labelInterval(curve.length),
        // 首尾标签贴边对齐，避免被画布边缘裁掉半个日期
        alignMinLabel: 'left', alignMaxLabel: 'right',
      },
      axisPointer: { label: { show: !mobile } },
    },
    yAxis: {
      type: 'value', scale: true, splitNumber: 5,
      min: (v: any) => v.min - (v.max - v.min) * 0.06,
      max: (v: any) => v.max + (v.max - v.min) * 0.14,
      axisLine: { show: false },
      axisTick: { show: false },
      // 刻度一律放在绘图区外：移动端曾用 inside 省宽度，结果标签与曲线/买卖点重叠
      axisLabel: mobile
        ? { formatter: navToWan, fontSize: 10, margin: 6, color: axisLabelColor }
        : { formatter: navToWan, fontSize: 11, margin: 10, color: axisLabelColor },
      splitLine: { lineStyle: { color: gridColor, type: 'dashed' } },
      axisPointer: { label: { formatter: (p: any) => navToWan(Number(p.value)) } },
    },
    series: [
      {
        name: '策略净值', type: 'line', data: navs,
        smooth: 0.2, showSymbol: false, symbol: 'circle', symbolSize: 5,
        lineStyle: {
          width: mobile ? 2 : 2.5, color: strategyColor,
          shadowColor: alpha(strategyColor, 0.35), shadowBlur: 10, shadowOffsetY: 5,
        },
        itemStyle: { color: strategyColor },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: alpha(strategyColor, 0.14) },
              { offset: 1, color: alpha(strategyColor, 0.01) },
            ],
          },
        },
        emphasis: { focus: 'series' },
        z: 5,
        // 最大回撤区间：历史最高点 → 之后最低点，仅作可视化标注
        ...(ddMax > 0.0005
          ? {
              markArea: {
                silent: true,
                itemStyle: { color: alpha('#f56c6c', isDark ? 0.16 : 0.12) },
                label: {
                  show: true,
                  // 区间靠右时贴右对齐，避免标签越过画布右边界被裁掉
                  position: ddCenter > 0.55 ? 'insideTopRight' : ddCenter < 0.45 ? 'insideTopLeft' : 'insideTop',
                  fontSize: mobile ? 10 : 11,
                  color: isDark ? '#e09a9a' : '#c45656',
                  formatter: `最大回撤 -${(ddMax * 100).toFixed(1)}%`,
                },
                data: [[{ xAxis: ddPeakIdx }, { xAxis: ddTroughIdx }]],
              },
            }
          : {}),
        // 初始资金基准线：一眼看出是否跑赢本金
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { color: axisLineColor, type: 'dashed', width: 1 },
          label: { show: false },
          data: [{ yAxis: baseNav }],
        },
        // 收益高点标注
        markPoint: {
          symbol: 'circle', symbolSize: mobile ? 6 : 7,
          itemStyle: { color: strategyColor, borderColor: isDark ? '#1b1d24' : '#fff', borderWidth: 1.5 },
          label: {
            // 峰值点与回撤区间标签都靠近图顶，峰值标签改放点下方避免叠字
            show: true, position: 'bottom', distance: 6,
            fontSize: mobile ? 10 : 11,
            color: isDark ? '#cfd3dd' : '#4a4f5c',
            backgroundColor: isDark ? 'rgba(27,29,36,0.9)' : 'rgba(255,255,255,0.92)',
            borderColor: axisLineColor, borderWidth: 1, borderRadius: 3, padding: [2, 4],
            formatter: (p: any) => `峰值 ${((Number(p.value) / baseNav - 1) * 100).toFixed(1)}%`,
          },
          data: [{ coord: [highIdx, navs[highIdx]], value: navs[highIdx] }],
        },
      },
      {
        name: '基准净值', type: 'line', data: curve.map((p: any) => p.benchmark),
        smooth: 0.2, showSymbol: false, symbol: 'none',
        lineStyle: { width: 1.4, color: benchmarkColor, type: 'dashed', opacity: 0.9 },
        itemStyle: { color: benchmarkColor }, z: 3,
      },
      {
        name: '买入', type: 'scatter', data: buyPoints,
        symbol: 'triangle', symbolSize: mobile ? 9 : 11,
        itemStyle: { color: '#f56c6c', borderColor: isDark ? '#1b1d24' : '#fff', borderWidth: 1 }, z: 10,
        tooltip: { show: false },
      },
      {
        name: '卖出', type: 'scatter', data: sellPoints,
        symbol: 'path://M-6,-6L6,6M6,-6L-6,6', symbolSize: mobile ? 8 : 10,
        itemStyle: { color: '#67c23a', borderColor: isDark ? '#1b1d24' : '#fff', borderWidth: 1 }, z: 10,
        tooltip: { show: false },
      },
    ],
  }
})

// ============ 初始化 ============
async function init() {
  try {
    const data = await strategyApi.getDataAvailability()
    dataAvailability.has_data = data.has_data
    dataAvailability.min_date = data.min_date || ''
    dataAvailability.max_date = data.max_date || ''
    if (data.min_date && data.max_date) {
      dateRange.value = [data.min_date, data.max_date]
      sectorDateRange.value = [data.min_date, data.max_date]
      overlayDateRange.value = [data.min_date, data.max_date]
    }
  } catch { /* ignore */ }
  try { sectorList.value = await settingsApi.getReplaySectors() } catch { /* ignore */ }
  await loadAvailableDates()
}

// 全局策略切换时同步回放策略
watch(() => strategyStore.currentStrategy, (v) => {
  overlayStrategyType.value = v
})

// 进入页面即加载历史寻优记录（后端已按时间倒序，最新在前）
onMounted(() => {
  loadOptimizeHistory()
  restoreTaskResult()
})

// 把寻优原始结果转换成叠加回放的结果格式（净值 + 每日明细 + 调仓快照）
function normalizeOptimizeResult(result: any) {
  const oos = result?.out_of_sample || null
  const byDate = (a: any[], b: any[]) => {
    const m = new Map<string, any>()
    for (const x of [...(a || []), ...(b || [])]) if (x?.date) m.set(x.date, x)
    return [...m.values()].sort((x, y) => String(x.date).localeCompare(String(y.date)))
  }
  const best = result?.best_result || {}
  return {
    daily_signals: byDate(best.daily_signals, oos?.daily_signals),
    nav_curve: byDate(best.nav_curve, oos?.nav_curve),
    summary: result?.combined_summary || best,
    position_changes: byDate(best.position_changes, oos?.position_changes),
    portfolio_snapshots: byDate(best.portfolio_snapshots, oos?.portfolio_snapshots),
  }
}

// 从 store 结果恢复页面展示（悬浮卡「查看回放详情」跳回、切页返回、刷新后都走这里）
function restoreTaskResult() {
  const t = replayTaskStore.task
  if (!t || t.status !== 'done' || !t.result) return
  replayMode.value = 'strategyOverlay'
  overlayData.value = t.mode === 'optimize' ? normalizeOptimizeResult(t.result) : t.result
  overlayStrategyType.value = t.strategyType
  overlayDateRange.value = [t.startDate, t.endDate]
  if (t.mode === 'optimize') {
    optimizeResult.value = t.result
    bestParams.value = t.result?.best_params
  }
}

// 后台任务在别的页面完成、或刷新续接完成后，页面在场时自动填入结果
watch(
  () => [replayTaskStore.task?.status, replayTaskStore.task?.result] as const,
  ([status, result]) => {
    if (status === 'done' && result && !overlayData.value) restoreTaskResult()
  },
)

onUnmounted(() => {
  stopAutoPlay()
  if (overlayZoomTimer) clearTimeout(overlayZoomTimer)
})
init()
</script>

<style lang="scss" scoped>
/* 寻优结果面板 */
.optimize-result,
.optimize-history {
  margin-top: 16px;
}
.best-params {
  margin: 8px 0 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}
.table-pagination {
  margin-top: 10px;
  justify-content: flex-end;
}
.replay-controls {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 0;
}
.control-date-range { width: 260px; max-width: 100%; }
.control-select { width: 160px; max-width: 100%; }
.control-select-wide { width: 200px; max-width: 100%; }
.control-select-small { width: 150px; max-width: 100%; }
.control-input-num { width: 140px; max-width: 100%; }
.control-input-num-small { width: 120px; max-width: 100%; }
.date-progress { font-size: 14px; color: var(--accent-primary); font-weight: 600; margin-left: 8px; }
.stat-box {
  text-align: center; padding: 16px 0;
  border-bottom: 1px solid var(--border-primary);
  .stat-value { font-family: var(--font-mono); font-size: 24px; font-weight: 600; color: var(--text-primary); }
  .stat-label { font-size: 12px; color: var(--text-tertiary); margin-top: 4px; }
  &.rise .stat-value { color: var(--accent-danger); }
  &.fall .stat-value { color: var(--accent-success); }
}
.card-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;
  .card-title { font-size: 18px; font-weight: 600; color: var(--text-primary); }
}
.params-display {
  margin-bottom: 12px; padding: 8px;
  background: var(--bg-tertiary); border-radius: var(--radius-sm);
}
.rebalance-group {
  margin-bottom: 16px; padding: 12px 0;
  border-bottom: 1px solid var(--border-primary);
}
.rebalance-date-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
  .rebalance-date { font-weight: 600; font-size: 14px; color: var(--text-primary); }
  .rebalance-cash { font-size: 12px; color: var(--text-tertiary); margin-left: auto; }
}
.rebalance-trades { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
.empty-portfolio { color: var(--text-tertiary); font-size: 13px; padding: 8px 0; }
/* 北向资金功能已停用：列置灰 */
.disabled-text { color: var(--text-tertiary); }
::deep(.col-disabled) { color: var(--text-tertiary) !important; }
::deep(.col-disabled .el-tag) { margin-left: 4px; transform: scale(0.85); }
.holding-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 2px 8px; margin: 2px 0; border-radius: 4px; font-size: 12px;
  background: var(--bg-secondary, #f5f6f8);
  .holding-etf { font-weight: 600; color: var(--text-primary); white-space: nowrap; }
  .holding-meta { color: var(--text-secondary); white-space: nowrap; }
}
:deep(.el-tabs__nav-wrap::after) { display: none; }

.flow-chart { height: var(--chart-h-lg); width: 100%; }
.sector-history-chart { height: var(--chart-h-lg); width: 100%; position: relative; touch-action: none; }
/* 策略净值曲线：桌面保留 420px 细节，移动端按 7.5.3 主图高度走令牌 */
.overlay-chart { height: 420px; width: 100%; }

/* K 线工具栏放到图表外，避免图例与 K 线争顶部空间 */
.kline-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.kline-ma { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.kline-ma.ma-hidden { opacity: .45; }
.ma-toggle,
.kline-legend-note {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 6px;
  border: 1px solid var(--border-primary, #e4e4e7);
  border-radius: 4px;
  background: var(--bg-secondary, #fff);
  color: var(--text-secondary, #71717a);
  font-size: 11px;
  line-height: 1;
  white-space: nowrap;
}
.ma-toggle { cursor: pointer; }
.ma-toggle.active { color: var(--text-primary, #27272a); border-color: var(--accent-primary, #637ee8); }
.ma-toggle:not(.active) { opacity: .45; text-decoration: line-through; }
.ma-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; }
.flow-dot { display: inline-block; width: 6px; height: 6px; border-radius: 2px; background: #f56c6c; }
.kline-gesture-tip { margin: 6px 0 0; font-size: 10px; line-height: 1.4; color: var(--text-tertiary, #a1a1aa); }
.kline-legend-note.disabled { color: var(--text-tertiary, #a1a1aa); text-decoration: line-through; }
/* 移动端自绘十字线：覆盖在图表上，不参与 ECharts 渲染 */
.kline-crosshair { position: absolute; inset: 0; pointer-events: none; z-index: 5; }
.kline-crosshair-line { display: none; position: absolute; top: 45px; bottom: 18%; border-left: 1px dashed #637ee8; }
.kline-crosshair-tip {
  display: none; position: absolute; top: 18px; left: 4px; max-width: calc(100% - 8px);
  padding: 3px 8px; border: 1px solid #e4e4e7; border-radius: 4px;
  background: rgba(255,255,255,.98); color: #27272a; font-size: 11px; line-height: 16px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; box-sizing: border-box;
}
.kh-date { color: #5a5f6e; }
.chart-placeholder { display: flex; align-items: center; justify-content: center; color: var(--text-tertiary); font-size: 12px; }

/* ─── 手机端：历史寻优记录 ─── */
.m-hist-list,
.m-sector-data {
  list-style: none;
  margin: 0;
  padding: 0;
}

.m-hist-row {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }
}

.m-hist-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;

  .m-hist-time { font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); }
}

.m-hist-grid,
.m-sd-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 4px;
  margin-top: 5px;

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

.m-hist-range { margin-top: 4px; font-size: 10px; color: var(--text-tertiary); font-family: var(--font-mono); }

.m-hist-detail {
  display: block;
  margin-top: 6px;
  padding: 4px 10px;
  border: 1px solid var(--accent-primary);
  border-radius: 4px;
  background: transparent;
  color: var(--accent-primary-text);
  font-size: 11px;
  font-family: var(--font-sans);
  cursor: pointer;

  &:hover { background: var(--accent-primary-light); }
}

/* ─── 手机端：每日板块数据 ─── */
.m-sector-data-row {
  padding: 7px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }
}

.m-sd-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;

  .m-sd-name {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .m-sd-change { font-size: 12px; font-weight: 600; font-family: var(--font-mono); }
}

.m-sd-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }

/* ─── 手机端：策略叠加 - 每日持仓条目 ─── */
.m-overlay-day-list,
.m-snap-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.m-od-row,
.m-snap-row {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);
  &:last-child { border-bottom: none; }
}

.m-od-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  .m-od-date { font-size: 12px; font-weight: 500; color: var(--text-primary); font-family: var(--font-mono); }
  .m-od-return { font-size: 13px; font-weight: 600; font-family: var(--font-mono); }
}

.m-od-positions,
.m-od-signals {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 5px;
}
.m-od-position {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-tertiary);
  font-size: 10px;
  color: var(--text-secondary);
}
.m-od-empty { font-size: 11px; color: var(--text-tertiary); }

.m-od-grid,
.m-snap-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 4px;
  margin-top: 5px;

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
.m-snap-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }

.m-snap-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  .m-snap-name { font-size: 12px; font-weight: 500; color: var(--text-primary); }
  .m-snap-weight { font-size: 12px; font-weight: 600; font-family: var(--font-mono); }
}

@media (max-width: 768px) {
  .stat-box { padding: 10px; .stat-value { font-size: 16px; } }
  .flow-chart { height: var(--chart-h-md); }
  .sector-history-chart { height: var(--chart-h-md); }
  .overlay-chart { height: var(--chart-h-md); }
  .card-header { flex-wrap: wrap; gap: 8px; }
  .replay-controls {
    :deep(.el-date-picker),
    :deep(.el-select),
    :deep(.el-input-number),
    :deep(.el-button) {
      max-width: 100%;
    }
  }
  :deep(.el-row) { margin-left: -8px !important; margin-right: -8px !important; }
  :deep(.el-col) { padding-left: 8px !important; padding-right: 8px !important; margin-bottom: 8px; }
}
@media (max-width: 480px) {
  /* 日期区间独占整行：EP 根节点不接受 class，用顶层 deep 结构选择器（见 02 文档 7.5.7） */
  :deep(.replay-controls > .el-date-editor--daterange) { grid-column: 1 / -1; width: 100% !important; }

  /* 规则7.5.2：控件紧凑网格，一屏可见多个控件；规则7.5.1：按钮12px */
  .replay-controls {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    padding: 8px 0;
    align-items: center;
    :deep(.el-divider--vertical) { display: none; }
    :deep(.el-button) { width: 100%; margin: 0; font-size: 12px; padding: 6px 8px; height: 32px; }
    :deep(.el-button .el-icon + span) { margin-left: 2px; }
    :deep(.el-input-number) { width: 100%; }
    > span { font-size: 11px; white-space: nowrap; }
  }
  .control-select-wide { grid-column: 1 / -1; }
  .date-progress { margin-left: 0; }
  .control-select,
  .control-select-small,
  .control-input-num,
  .control-input-num-small { width: 100%; }
  .stat-box {
    padding: 8px;
    .stat-value { font-size: 17px; }
    /* 领涨板块一格里放的是板块名，长文本必须降字号否则撑破方格 */
    .stat-value.name { font-size: 13px; line-height: 1.3; word-break: break-all; }
    .stat-label { font-size: 10px; }
  }
  .card-header { flex-direction: column; align-items: stretch; gap: 6px; }

  /* 雪球式工具栏：周期四等分 + 均线开关第二行，触控高度 32px；
     分段样式（高/内边距/字号/等分）统一由 mobile.scss 的 .fill 规范负责 */
  .kline-toolbar { flex-direction: column; align-items: stretch; gap: 6px; }
  .kline-period { display: grid; grid-template-columns: repeat(4, 1fr); width: 100%; }
  .kline-ma { width: 100%; }
  .ma-toggle, .kline-legend-note {
    height: var(--m-tap, 32px);
    flex: 1 1 auto;
    justify-content: center;
  }

  .stat-grid :deep(.el-col) { margin-bottom: 6px; }
  :deep(.el-tabs__item) { font-size: 12px; padding: 0 10px; }
  .params-display {
    font-size: 11px;
    /* 长参数串在窄屏必须换行，禁止被裁切 */
    :deep(.el-tag) { height: auto; white-space: normal; line-height: 1.5; }
  }
  .date-progress { font-size: 11px; }
  :deep(.el-row) { margin-left: -4px !important; margin-right: -4px !important; }
  :deep(.el-col) { padding-left: 4px !important; padding-right: 4px !important; margin-bottom: 6px; }
}
</style>
