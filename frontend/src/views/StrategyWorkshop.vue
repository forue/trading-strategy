<template>
  <div class="ws-page">
    <div class="ws-head">
      <div>
        <h2><el-icon><component is="MagicStick" /></el-icon> 策略工坊</h2>
        <p>创建自己的策略：设定适用场景、触发条件、执行动作与风控参数，保存版本后应用到回测或当日信号。</p>
      </div>
      <el-button v-if="tab === 'algorithms'" type="primary" @click="openAlgorithmCreate">新建算法</el-button>
      <el-button v-else type="primary" @click="openCreate">新建策略</el-button>
    </div>

    <el-tabs v-model="tab" class="ws-tabs" @tab-change="onTabChange">
      <el-tab-pane label="我的策略" name="mine" />
      <el-tab-pane label="公开广场" name="public" />
      <el-tab-pane label="我的算法" name="algorithms" />
      <el-tab-pane label="运行记录" name="runs" />
    </el-tabs>
    <p v-if="tab === 'public'" class="ws-hint ws-sort-hint">按点赞量从高到低排序；同一账号对同一策略只能点赞一次，再次点击可取消。</p>

    <div v-if="tab === 'algorithms'" class="ws-grid">
      <div v-if="!algorithms.length" class="ws-empty">还没有自建算法。算法是一组可复用的触发条件，可一键插入到任意策略。</div>
      <div v-for="alg in algorithms" :key="alg.id" class="ws-card">
        <div class="ws-card-head">
          <div class="ws-title-row"><h3>{{ alg.name }}</h3><el-tag size="small" effect="plain">自建算法</el-tag></div>
        </div>
        <p class="ws-desc">{{ alg.description || '暂无算法说明' }}</p>
        <div class="ws-rule-summary">
          <span v-for="(c, i) in alg.conditions" :key="i" class="ws-chip">
            {{ fieldText(c.field) }} {{ opText(c.op) }} {{ c.value }}
          </span>
          <span v-if="!alg.conditions.length" class="ws-muted">未设置条件</span>
        </div>
        <div class="ws-card-actions">
          <div class="ws-action-grid">
            <el-button size="small" @click="openAlgorithmEdit(alg)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="removeAlgorithm(alg)">删除</el-button>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="tab === 'runs'" class="ws-runs">
      <div v-if="!runs.length" class="ws-empty">还没有运行记录。打开策略卡片上的「应用」开始一次回测或当日运行。</div>
      <div v-for="run in runs" :key="run.id" class="ws-run-card">
        <div class="ws-run-head">
          <strong>{{ runName(run.strategy_id) }}</strong>
          <el-tag :type="run.status === 'success' ? 'success' : 'danger'" size="small">
            {{ run.status === 'success' ? '成功' : '失败' }}
          </el-tag>
          <el-tag size="small" effect="plain">{{ run.mode === 'simulation' ? '模拟回测' : '实际环境' }}</el-tag>
          <span class="ws-muted">{{ formatTime(run.started_at) }}</span>
        </div>
        <div v-if="run.status === 'success' && run.result" class="ws-run-summary">
          <template v-if="run.mode === 'simulation'">
            <span>总收益 <b :class="trendClass(run.result.total_return)">{{ pct(run.result.total_return) }}</b></span>
            <span>最大回撤 <b class="ws-loss">{{ pct(run.result.max_drawdown) }}</b></span>
            <span>夏普 <b>{{ number(run.result.sharpe_ratio) }}</b></span>
            <span>交易 <b>{{ run.result.trade_count ?? '-' }}</b></span>
          </template>
          <template v-else>
            <span>信号日 <b>{{ run.result.signal_date || '-' }}</b></span>
            <span>生成 <b>{{ run.result.stats?.generated ?? 0 }}</b></span>
            <span>过滤 <b>{{ run.result.stats?.filtered ?? 0 }}</b></span>
            <span>采纳 <b>{{ run.result.stats?.accepted ?? 0 }}</b></span>
          </template>
        </div>
        <div v-else class="ws-error">{{ run.error || '运行失败' }}</div>
      </div>
    </div>

    <div v-else class="ws-grid">
      <div v-if="tab === 'mine' && !mine.length" class="ws-empty">
        还没有自定义策略。点击右上角「新建策略」开始。
      </div>
      <div v-if="tab === 'public' && !publicList.length" class="ws-empty">
        暂无公开的分享策略。把自己的策略设为公开后，它就会出现在广场，其他账号也能浏览并复制。
      </div>

      <div v-for="s in tab === 'mine' ? mine : publicList" :key="s.id" class="ws-card">
        <div class="ws-card-head">
          <div class="ws-title-row">
            <h3>{{ s.name }}</h3>
            <el-tag v-if="s.is_public" type="success" size="small">公开</el-tag>
            <el-tag v-else size="small" effect="plain">私有</el-tag>
            <el-tag :type="statusTag(s.status)" size="small">{{ statusText(s.status) }}</el-tag>
            <el-tag v-if="s.is_owner" size="small" effect="plain">我的</el-tag>
          </div>
          <span class="ws-version">v{{ s.version }}</span>
        </div>
        <p class="ws-desc">{{ s.description || '暂无策略说明' }}</p>
        <div class="ws-meta">
          <span>场景：<b>{{ scenarioText(s.scenario) }}</b></span>
          <span>条件 <b>{{ s.conditions?.length || 0 }}</b> / 动作 <b>{{ s.actions?.length || 0 }}</b></span>
          <span v-if="tab === 'public'">作者：<b>{{ s.owner_name || '-' }}</b></span>
          <span v-else>运行 <b>{{ s.run_count ?? 0 }}</b> 次 · 版本 <b>{{ s.version_count ?? 0 }}</b></span>
        </div>
        <div class="ws-rule-summary">
          <span v-for="(c, i) in (s.conditions || []).slice(0, 2)" :key="'c' + i" class="ws-chip">
            {{ fieldText(c.field) }} {{ opText(c.op) }} {{ c.value }}
          </span>
          <span v-for="(a, i) in (s.actions || []).slice(0, 1)" :key="'a' + i" class="ws-chip ws-chip-action">
            {{ actionText(a.type) }} {{ a.value }}
          </span>
          <span v-if="!(s.conditions || []).length && !(s.actions || []).length" class="ws-muted">未设置条件与动作</span>
        </div>
        <div class="ws-card-actions">
          <template v-if="tab === 'mine'">
            <el-button type="primary" class="ws-action-primary" @click="openRun(s)">应用策略</el-button>
            <div class="ws-action-grid">
              <el-button size="small" @click="openEdit(s)">编辑</el-button>
              <el-button size="small" @click="openVersions(s)">版本</el-button>
              <el-button size="small" @click="togglePublic(s)">{{ s.is_public ? '取消公开' : '公开分享' }}</el-button>
              <el-button size="small" type="danger" plain @click="removeStrategy(s)">删除</el-button>
            </div>
          </template>
          <template v-else>
            <el-button v-if="s.is_owner" type="primary" class="ws-action-primary" @click="openEdit(s)">编辑我的策略</el-button>
            <el-button v-else type="primary" class="ws-action-primary" @click="forkStrategy(s)">复制到我的策略</el-button>
            <div class="ws-action-grid">
              <el-button size="small" @click="openDetail(s)">查看配置</el-button>
              <el-button size="small" :type="s.liked_by_me ? 'primary' : undefined" plain @click="toggleLike(s)">
                <el-icon><component :is="s.liked_by_me ? 'StarFilled' : 'Star'" /></el-icon>
                {{ s.liked_by_me ? '已赞' : '点赞' }} {{ s.like_count ?? 0 }}
              </el-button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 策略编辑器 -->
    <el-drawer v-model="editorOpen" :title="editingId ? '编辑策略' : detailMode ? '策略详情' : '新建策略'" size="min(640px, 100%)">
      <el-form :model="form" label-position="top" :disabled="detailMode">
        <el-form-item label="策略名称" required>
          <el-input v-model="form.name" maxlength="80" placeholder="例如：强势板块低吸策略" />
        </el-form-item>
        <el-form-item label="适用场景">
          <el-select v-model="form.scenario" style="width: 100%">
            <el-option label="激进（短线高弹性）" value="AGGRESSIVE" />
            <el-option label="稳健（均衡轮动）" value="MODERATE" />
            <el-option label="保守（低波动防守）" value="CONSERVATIVE" />
          </el-select>
        </el-form-item>
        <el-form-item label="策略说明">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="500" placeholder="记录策略思路与适用行情" />
        </el-form-item>
        <el-form-item label="运行状态">
          <el-radio-group v-model="form.status" class="fill">
            <el-radio-button value="draft">草稿</el-radio-button>
            <el-radio-button value="active">启用</el-radio-button>
            <el-radio-button value="paused">暂停</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <div class="ws-section-title">
          <span>触发条件</span>
          <div class="ws-section-actions">
            <el-select v-model="algorithmChoice" size="small" class="ws-algo-select" placeholder="插入算法" clearable :disabled="detailMode" @change="applyAlgorithm">
              <el-option-group label="系统内置">
                <el-option v-for="a in builtinAlgorithms" :key="a.id" :label="a.name" :value="`b:${a.id}`" />
              </el-option-group>
              <el-option-group label="我的算法">
                <el-option v-for="a in algorithms" :key="a.id" :label="a.name" :value="`m:${a.id}`" />
              </el-option-group>
            </el-select>
            <el-button size="small" :disabled="detailMode" @click="addCondition">添加条件</el-button>
          </div>
        </div>
        <div class="ws-condition-mode">
          <span>组合方式</span>
          <el-radio-group v-model="form.condition_logic" size="small" class="fill">
            <el-radio-button value="AND">同时满足</el-radio-button>
            <el-radio-button value="OR">任一满足</el-radio-button>
          </el-radio-group>
        </div>
        <p class="ws-hint">算法是一组可复用的触发条件，可一键插入。信号方向指引擎给出的 BUY（买入/加仓）或 SELL（卖出/清仓，常见于止损或市场转弱），选 SELL 即只保留卖出信号。行情/估值条件在实际环境运行时按当日板块数据匹配，回测不逐日应用。</p>
        <el-alert v-if="conditionConflicts.length" type="warning" :closable="false" show-icon class="ws-conflict"
          :title="`检测到条件冲突：${conditionConflicts.join('；')}`" />
        <div v-for="(c, i) in form.conditions" :key="'cond' + i" class="ws-rule-row">
          <el-select v-model="c.field" size="small" class="ws-field" @change="onConditionFieldChange(c)">
            <el-option v-for="f in conditionFields" :key="f.value" :label="f.label" :value="f.value" />
          </el-select>
          <el-select v-model="c.op" size="small" class="ws-op">
            <el-option v-for="o in conditionOps" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-select v-if="c.field === 'direction'" v-model="c.value" size="small" class="ws-value">
            <el-option label="买入 BUY" value="BUY" />
            <el-option label="卖出 SELL" value="SELL" />
          </el-select>
          <el-input v-else-if="isTextCondition(c.field)" v-model="c.value" size="small" class="ws-value" placeholder="板块名称/代码" />
          <el-input-number v-else v-model="c.value" size="small" class="ws-value" :controls="false" :precision="3" />
          <el-button size="small" :disabled="detailMode" @click="form.conditions.splice(i, 1)">删除</el-button>
        </div>

        <div class="ws-section-title">
          <span>执行动作</span>
          <el-button size="small" :disabled="detailMode" @click="addAction">添加动作</el-button>
        </div>
        <p class="ws-hint">条件命中后按列表顺序调整信号；仓位比例用 0~1 小数（0.3 表示 30%）。</p>
        <el-alert v-if="actionConflicts.length" type="warning" :closable="false" show-icon class="ws-conflict"
          :title="`检测到动作冲突：${actionConflicts.join('；')}`" />
        <div v-for="(a, i) in form.actions" :key="'act' + i" class="ws-rule-row">
          <el-select v-model="a.type" size="small" class="ws-field" @change="onActionTypeChange(a)">
            <el-option v-for="act in actionTypes" :key="act.value" :label="act.label" :value="act.value" />
          </el-select>
          <el-select v-if="a.type === 'force_direction'" v-model="a.value" size="small" class="ws-value">
            <el-option label="买入 BUY" value="BUY" />
            <el-option label="卖出 SELL" value="SELL" />
          </el-select>
          <el-input-number v-else-if="a.type === 'set_position_ratio'" v-model="a.value" size="small" class="ws-value" :min="0" :max="1" :step="0.05" :precision="2" />
          <el-input v-else v-model="a.value" size="small" class="ws-value" placeholder="板块名称" />
          <el-button size="small" :disabled="detailMode" @click="form.actions.splice(i, 1)">删除</el-button>
        </div>

        <div class="ws-section-title"><span>风险控制参数</span></div>
        <p class="ws-hint">比例用 0~1 小数；未填写的项沿用当前账号该场景的策略配置。</p>
        <div class="ws-risk-grid">
          <el-form-item v-for="item in riskFields" :key="item.key" :label="item.label">
            <el-input-number v-model="riskForm[item.key]" size="small" :min="item.min" :max="item.max" :step="item.step" :precision="item.precision" controls-position="right" placeholder="沿用默认" />
          </el-form-item>
        </div>

        <el-form-item v-if="!detailMode" label="版本说明">
          <el-input v-model="changeNote" maxlength="200" placeholder="可选：这次修改了什么" />
        </el-form-item>
        <el-form-item v-if="!detailMode">
          <el-checkbox v-model="form.is_public">公开分享（其他人可在公开广场浏览并复制）</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorOpen = false">{{ detailMode ? '关闭' : '取消' }}</el-button>
        <el-button v-if="!detailMode" type="primary" :loading="saving" @click="saveStrategy">保存策略</el-button>
      </template>
    </el-drawer>

    <!-- 版本记录 -->
    <el-drawer v-model="versionsOpen" title="版本记录" size="min(520px, 100%)">
      <div v-if="!versions.length" class="ws-empty">暂无版本记录</div>
      <div v-for="v in versions" :key="v.version" class="ws-version-row">
        <div>
          <strong>v{{ v.version }}</strong>
          <span class="ws-muted">{{ formatTime(v.created_at) }}</span>
          <p>{{ v.change_note }}</p>
          <small class="ws-muted">{{ snapshotText(v.snapshot) }}</small>
        </div>
        <el-button size="small" @click="restoreVersion(v)">载入编辑</el-button>
      </div>
    </el-drawer>

    <!-- 自建算法编辑 -->
    <el-dialog v-model="algorithmOpen" :title="algorithmId ? '编辑算法' : '新建算法'" width="min(560px, 100%)">
      <el-form :model="algorithmForm" label-position="top">
        <el-form-item label="算法名称" required>
          <el-input v-model="algorithmForm.name" maxlength="80" placeholder="例如：资金流强势确认" />
        </el-form-item>
        <el-form-item label="算法说明">
          <el-input v-model="algorithmForm.description" type="textarea" :rows="2" maxlength="500" placeholder="记录该算法的适用行情" />
        </el-form-item>
        <div class="ws-section-title">
          <span>触发条件</span>
          <el-button size="small" @click="addAlgorithmCondition">添加条件</el-button>
        </div>
        <p class="ws-hint">保存后可在策略编辑器里一键插入；字段与触发条件一致。</p>
        <div v-for="(c, i) in algorithmForm.conditions" :key="'algcond' + i" class="ws-rule-row">
          <el-select v-model="c.field" size="small" class="ws-field" @change="onConditionFieldChange(c)">
            <el-option v-for="f in conditionFields" :key="f.value" :label="f.label" :value="f.value" />
          </el-select>
          <el-select v-model="c.op" size="small" class="ws-op">
            <el-option v-for="o in conditionOps" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-select v-if="c.field === 'direction'" v-model="c.value" size="small" class="ws-value">
            <el-option label="买入 BUY" value="BUY" />
            <el-option label="卖出 SELL" value="SELL" />
          </el-select>
          <el-input v-else-if="isTextCondition(c.field)" v-model="c.value" size="small" class="ws-value" placeholder="板块名称/代码" />
          <el-input-number v-else v-model="c.value" size="small" class="ws-value" :controls="false" :precision="3" />
          <el-button size="small" @click="algorithmForm.conditions.splice(i, 1)">删除</el-button>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="algorithmOpen = false">取消</el-button>
        <el-button type="primary" @click="saveAlgorithm">保存算法</el-button>
      </template>
    </el-dialog>

    <!-- 应用运行 -->
    <el-drawer v-model="runOpen" title="应用策略" size="min(720px, 100%)" @closed="disposeChart">
      <div class="ws-run-form">
        <el-radio-group v-model="runForm.mode">
          <el-radio-button value="simulation">模拟回测</el-radio-button>
          <el-radio-button value="live">实际环境（当日信号）</el-radio-button>
        </el-radio-group>
        <template v-if="runForm.mode === 'simulation'">
          <el-date-picker v-model="runForm.start_date" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" />
          <el-date-picker v-model="runForm.end_date" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" />
          <el-input-number v-model="runForm.initial_capital" :min="10000" :step="100000" controls-position="right" />
        </template>
        <el-button type="primary" :loading="applying" @click="doApply">开始运行</el-button>
      </div>
      <p class="ws-hint">
        模拟回测按风控参数逐日回放历史；实际环境运行当日策略计算并沿用既有信号链路，工坊规则会过滤/调整本次采纳的信号。
        系统未对接券商通道，实际环境指本地持仓账本口径。
      </p>

      <template v-if="runResult">
        <div v-if="runForm.mode === 'simulation'" class="ws-metrics">
          <div><span>总收益</span><b :class="trendClass(runResult.total_return)">{{ pct(runResult.total_return) }}</b></div>
          <div><span>年化收益</span><b :class="trendClass(runResult.annual_return)">{{ pct(runResult.annual_return) }}</b></div>
          <div><span>最大回撤</span><b class="ws-loss">{{ pct(runResult.max_drawdown) }}</b></div>
          <div><span>夏普比率</span><b>{{ number(runResult.sharpe_ratio) }}</b></div>
          <div><span>胜率</span><b>{{ pct(runResult.win_rate) }}</b></div>
          <div><span>交易次数</span><b>{{ runResult.trade_count ?? '-' }}</b></div>
        </div>
        <div v-else class="ws-metrics">
          <div><span>信号日</span><b>{{ runResult.signal_date || '-' }}</b></div>
          <div><span>生成信号</span><b>{{ runResult.stats?.generated ?? 0 }}</b></div>
          <div><span>条件过滤</span><b>{{ runResult.stats?.filtered ?? 0 }}</b></div>
          <div><span>最终采纳</span><b>{{ runResult.stats?.accepted ?? 0 }}</b></div>
        </div>
        <div v-if="runResult.nav_curve?.length" ref="navEl" class="ws-nav-chart" />
        <div v-if="runResult.signals?.length" class="ws-signal-list">
          <h4>采纳信号</h4>
          <div v-for="(sig, i) in runResult.signals" :key="i" class="ws-signal-row">
            <el-tag :type="sig.direction === 'BUY' ? 'danger' : 'success'" size="small">{{ sig.direction }}</el-tag>
            <strong>{{ sig.sector_name }}</strong>
            <span>评分 {{ number(sig.score) }} · 仓位 {{ pct(sig.position_ratio) }}</span>
            <small>{{ sig.reason }}</small>
          </div>
        </div>
        <p v-if="runResult.note" class="ws-hint">{{ runResult.note }}</p>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import {
  workshopApi,
  type WorkshopAction,
  type WorkshopAlgorithm,
  type WorkshopCondition,
  type WorkshopPayload,
  type WorkshopRun,
  type WorkshopStrategy,
  type WorkshopVersion,
} from '@/api/workshop'

const conditionFields = [
  { value: 'score', label: '策略评分' },
  { value: 'position_ratio', label: '建议仓位' },
  { value: 'rank', label: '板块排名' },
  { value: 'direction', label: '信号方向' },
  { value: 'index_change_pct', label: '当日涨跌幅(%)' },
  { value: 'main_net_inflow', label: '主力净流入(元)' },
  { value: 'turnover', label: '换手率(%)' },
  { value: 'pe_percentile', label: 'PE分位(%)' },
  { value: 'pb_percentile', label: 'PB分位(%)' },
  { value: 'sector_code', label: '板块代码' },
  { value: 'sector_name', label: '板块名称' },
]
const conditionOps = [
  { value: 'gt', label: '大于' }, { value: 'gte', label: '大于等于' },
  { value: 'lt', label: '小于' }, { value: 'lte', label: '小于等于' },
  { value: 'eq', label: '等于' }, { value: 'contains', label: '包含' },
]
const actionTypes = [
  { value: 'set_position_ratio', label: '仓位上限' },
  { value: 'force_direction', label: '强制方向' },
  { value: 'exclude_sector', label: '排除板块' },
  { value: 'include_only_sector', label: '仅保留板块' },
]
// 字段切换时联动重置运算符与默认值，避免旧值残留导致条件语义错误
const defaultOpByField: Record<string, string> = {
  score: 'gte', position_ratio: 'gte', rank: 'lte', direction: 'eq',
  index_change_pct: 'gte', main_net_inflow: 'gte', turnover: 'gte',
  pe_percentile: 'lte', pb_percentile: 'lte',
  sector_code: 'contains', sector_name: 'contains',
}
const defaultValueByField: Record<string, any> = {
  score: 5, position_ratio: 0.3, rank: 3, direction: 'BUY',
  index_change_pct: 2, main_net_inflow: 50000000, turnover: 2,
  pe_percentile: 40, pb_percentile: 40, sector_code: '', sector_name: '',
}
const riskFields = [
  { key: 'top_n', label: '选股数量', min: 1, max: 20, step: 1, precision: 0 },
  { key: 'hold_days', label: '持有天数', min: 1, max: 120, step: 1, precision: 0 },
  { key: 'max_position', label: '单板块最大仓位', min: 0, max: 1, step: 0.05, precision: 2 },
  { key: 'capital_pct', label: '单次投入资金比例', min: 0, max: 1, step: 0.05, precision: 2 },
  { key: 'stop_loss', label: '固定止损', min: 0, max: 1, step: 0.01, precision: 3 },
  { key: 'trailing_stop_loss', label: '移动止损', min: 0, max: 1, step: 0.01, precision: 3 },
  { key: 'max_drawdown_stop', label: '最大回撤止损', min: 0, max: 1, step: 0.01, precision: 3 },
  { key: 'min_score_threshold', label: '最低评分门槛', min: 0, max: 100, step: 0.5, precision: 2 },
]

const tab = ref<'mine' | 'public' | 'algorithms' | 'runs'>('mine')
const mine = ref<WorkshopStrategy[]>([])
const publicList = ref<WorkshopStrategy[]>([])
const runs = ref<WorkshopRun[]>([])
const loading = ref(false)
const algorithms = ref<WorkshopAlgorithm[]>([])
const builtinAlgorithms = ref<WorkshopAlgorithm[]>([])
const algorithmChoice = ref('')
const algorithmOpen = ref(false)
const algorithmId = ref<number | null>(null)
const emptyAlgorithm = (): Omit<WorkshopAlgorithm, 'id'> => ({ name: '', description: '', conditions: [] })
const algorithmForm = ref<Omit<WorkshopAlgorithm, 'id'>>(emptyAlgorithm())

const editorOpen = ref(false)
const editingId = ref<number | null>(null)
const detailMode = ref(false)
const saving = ref(false)
const changeNote = ref('')
const emptyForm = (): WorkshopPayload => ({
  name: '', scenario: 'MODERATE', description: '', condition_logic: 'AND',
  conditions: [], actions: [], risk: {}, is_public: false, status: 'draft',
})
const form = ref<WorkshopPayload>(emptyForm())
const riskForm = reactive<Record<string, number | undefined>>({})

const versionsOpen = ref(false)
const versions = ref<WorkshopVersion[]>([])
const versionFor = ref<WorkshopStrategy | null>(null)

const runOpen = ref(false)
const applying = ref(false)
const runFor = ref<WorkshopStrategy | null>(null)
const runForm = reactive({ mode: 'simulation' as 'simulation' | 'live', start_date: '', end_date: '', initial_capital: 1000000 })
const runResult = ref<Record<string, any> | null>(null)
const navEl = ref<HTMLElement | null>(null)
let navChart: echarts.ECharts | null = null

function isTextCondition(field: string) { return field === 'sector_code' || field === 'sector_name' }
function scenarioText(v: string) { return { AGGRESSIVE: '激进', MODERATE: '稳健', CONSERVATIVE: '保守' }[v] || v }
function statusText(v: string) { return { draft: '草稿', active: '启用', paused: '暂停' }[v] || v }
function statusTag(v: string) { return v === 'active' ? 'success' : v === 'paused' ? 'warning' : 'info' }
function fieldText(v: string) { return conditionFields.find(f => f.value === v)?.label || v }
function opText(v: string) { return conditionOps.find(o => o.value === v)?.label || v }
function actionText(v: string) { return actionTypes.find(a => a.value === v)?.label || v }

const numericConditionFields = new Set([
  'score', 'position_ratio', 'rank', 'index_change_pct', 'main_net_inflow',
  'turnover', 'pe_percentile', 'pb_percentile',
])
const conditionKey = (c: WorkshopCondition) => `${c.field}|${c.op}|${c.value}`
const conditionConflicts = computed(() => {
  const list = form.value.conditions || []
  const out: string[] = []
  const seen = new Set<string>()
  for (const c of list) {
    if (seen.has(conditionKey(c))) out.push(`重复条件「${fieldText(c.field)} ${opText(c.op)} ${c.value}」`)
    seen.add(conditionKey(c))
  }
  if (form.value.condition_logic === 'AND') {
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const a = list[i], b = list[j]
        if (a.field !== b.field || !numericConditionFields.has(a.field)) continue
        const av = Number(a.value), bv = Number(b.value)
        const impossible =
          (a.op === 'gte' && b.op === 'lte' && av > bv) || (a.op === 'lte' && b.op === 'gte' && bv > av) ||
          (a.op === 'gt' && b.op === 'lt' && av >= bv) || (a.op === 'lt' && b.op === 'gt' && bv >= av)
        if (impossible) out.push(`「${fieldText(a.field)} ${opText(a.op)} ${av}」与「${opText(b.op)} ${bv}」无法同时满足`)
      }
    }
  }
  return out.slice(0, 3)
})
const actionConflicts = computed(() => {
  const list = form.value.actions || []
  const out: string[] = []
  const seen = new Set<string>()
  for (const a of list) {
    if (seen.has(a.type)) out.push(`重复的「${actionText(a.type)}」动作，后面的会覆盖前面`)
    seen.add(a.type)
  }
  if (list.some(a => a.type === 'exclude_sector') && list.some(a => a.type === 'include_only_sector')) {
    out.push('「排除板块」与「仅保留板块」同时存在，以后者为准')
  }
  return out
})
function pct(v: any) { return v === null || v === undefined ? '-' : `${(Number(v) * 100).toFixed(2)}%` }
function number(v: any) { return v === null || v === undefined ? '-' : Number(v).toFixed(2) }
function trendClass(v: any) { return Number(v) >= 0 ? 'ws-gain' : 'ws-loss' }
function formatTime(v?: string) { return v ? v.replace('T', ' ').slice(0, 19) : '-' }
function runName(id: number) { return mine.value.find(s => s.id === id)?.name || `策略 #${id}` }
function snapshotText(s: WorkshopPayload) {
  return `${s.scenario} · 条件 ${s.conditions?.length || 0} 条 · 动作 ${s.actions?.length || 0} 条 · ${s.description || '无说明'}`
}

function fillForm(s: WorkshopPayload) {
  form.value = {
    name: s.name, scenario: s.scenario, description: s.description,
    condition_logic: s.condition_logic || 'AND',
    conditions: (s.conditions || []).map(c => ({ ...c })),
    actions: (s.actions || []).map(a => ({ ...a })),
    risk: { ...(s.risk || {}) }, is_public: s.is_public, status: s.status,
  }
  for (const item of riskFields) riskForm[item.key] = form.value.risk[item.key] as number | undefined
}
function collectRisk() {
  const risk: Record<string, number> = {}
  for (const item of riskFields) {
    const value = riskForm[item.key]
    if (value !== undefined && value !== null) risk[item.key] = value
  }
  return risk
}
function newCondition(): WorkshopCondition {
  return { field: 'score', op: defaultOpByField.score, value: defaultValueByField.score }
}
function onConditionFieldChange(c: WorkshopCondition) {
  c.op = defaultOpByField[c.field] || 'gte'
  c.value = defaultValueByField[c.field] ?? 0
}
function onActionTypeChange(a: WorkshopAction) {
  a.value = a.type === 'set_position_ratio' ? 0.3 : a.type === 'force_direction' ? 'BUY' : ''
}
function addCondition() { form.value.conditions.push(newCondition()) }
function addAlgorithmCondition() { algorithmForm.value.conditions.push(newCondition()) }
function addAction() {
  form.value.actions.push({ type: 'set_position_ratio', value: 0.3 } as WorkshopAction)
}
function applyAlgorithm(value: string) {
  if (!value) return
  const list = value.startsWith('b:') ? builtinAlgorithms.value : algorithms.value
  const alg = list.find(a => String(a.id) === value.slice(2))
  if (alg) {
    const seen = new Set(form.value.conditions.map(conditionKey))
    const incoming = alg.conditions.map(c => ({ ...c })).filter(c => {
      const key = conditionKey(c)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    form.value.conditions.push(...incoming)
    const skipped = alg.conditions.length - incoming.length
    if (skipped) ElMessage.warning(`已跳过 ${skipped} 条与现有条件重复的规则`)
    else ElMessage.success(`已插入「${alg.name}」的 ${incoming.length} 条条件`)
    if (incoming.length && form.value.condition_logic === 'AND' && form.value.conditions.length > incoming.length) {
      ElMessage.warning('多个算法默认按「同时满足」叠加，过于严格时可切换为「任一满足」')
    }
  }
  algorithmChoice.value = ''
}

async function loadMine() {
  loading.value = true
  try { mine.value = await workshopApi.list('mine') } finally { loading.value = false }
}
async function loadPublic() {
  loading.value = true
  try { publicList.value = await workshopApi.list('public') } finally { loading.value = false }
}
async function loadRuns() {
  loading.value = true
  try { runs.value = await workshopApi.listRuns() } finally { loading.value = false }
}
async function loadAlgorithms() {
  loading.value = true
  try {
    const [mineAlgorithms, builtin] = await Promise.all([
      workshopApi.listAlgorithms(), workshopApi.builtinAlgorithms(),
    ])
    algorithms.value = mineAlgorithms
    builtinAlgorithms.value = builtin
  } finally { loading.value = false }
}
function onTabChange(name: string | number) {
  if (name === 'public' && !publicList.value.length) loadPublic()
  if (name === 'algorithms') loadAlgorithms()
  if (name === 'runs') loadRuns()
}

function openAlgorithmCreate() {
  algorithmId.value = null
  algorithmForm.value = emptyAlgorithm()
  algorithmOpen.value = true
}
function openAlgorithmEdit(alg: WorkshopAlgorithm) {
  algorithmId.value = typeof alg.id === 'number' ? alg.id : null
  algorithmForm.value = {
    name: alg.name, description: alg.description,
    conditions: alg.conditions.map(c => ({ ...c })),
  }
  algorithmOpen.value = true
}
async function saveAlgorithm() {
  if (!algorithmForm.value.name.trim()) { ElMessage.warning('请填写算法名称'); return }
  if (algorithmId.value) await workshopApi.updateAlgorithm(algorithmId.value, algorithmForm.value)
  else await workshopApi.createAlgorithm(algorithmForm.value)
  ElMessage.success('算法已保存')
  algorithmOpen.value = false
  await loadAlgorithms()
}
async function removeAlgorithm(alg: WorkshopAlgorithm) {
  if (typeof alg.id !== 'number') return
  try {
    await ElMessageBox.confirm(`确认删除算法「${alg.name}」？已插入策略的条件不受影响。`, '删除算法', { type: 'warning' })
  } catch { return }
  await workshopApi.deleteAlgorithm(alg.id)
  ElMessage.success('算法已删除')
  await loadAlgorithms()
}

function openCreate() {
  editingId.value = null
  detailMode.value = false
  changeNote.value = ''
  fillForm(emptyForm())
  editorOpen.value = true
}
function openEdit(s: WorkshopStrategy) {
  editingId.value = s.id
  detailMode.value = false
  changeNote.value = ''
  fillForm(s)
  editorOpen.value = true
}
function openDetail(s: WorkshopStrategy) {
  editingId.value = s.id
  detailMode.value = true
  fillForm(s)
  editorOpen.value = true
}
async function saveStrategy() {
  if (!form.value.name.trim()) { ElMessage.warning('请填写策略名称'); return }
  saving.value = true
  try {
    const payload: WorkshopPayload = { ...form.value, risk: collectRisk() }
    if (editingId.value) await workshopApi.update(editingId.value, payload, changeNote.value)
    else await workshopApi.create(payload)
    ElMessage.success(editingId.value ? '策略已保存，版本已更新' : '策略已创建')
    if (actionConflicts.value.length) ElMessage.warning(`动作存在冲突：${actionConflicts.value.join('；')}`)
    editorOpen.value = false
    await loadMine()
  } finally { saving.value = false }
}
async function togglePublic(s: WorkshopStrategy) {
  const payload: WorkshopPayload = {
    name: s.name, scenario: s.scenario, description: s.description,
    condition_logic: s.condition_logic || 'AND',
    conditions: s.conditions, actions: s.actions, risk: s.risk,
    is_public: !s.is_public, status: s.status,
  }
  await workshopApi.update(s.id, payload, s.is_public ? '取消公开' : '公开分享')
  ElMessage.success(s.is_public ? '已取消公开' : '已公开到分享广场')
  await loadMine()
  publicList.value = []
}
async function removeStrategy(s: WorkshopStrategy) {
  try {
    await ElMessageBox.confirm(`确认删除「${s.name}」？版本与运行记录会一并删除。`, '删除策略', { type: 'warning' })
  } catch { return }
  await workshopApi.remove(s.id)
  ElMessage.success('策略已删除')
  await loadMine()
}
async function forkStrategy(s: WorkshopStrategy) {
  await workshopApi.fork(s.id)
  ElMessage.success('已复制到我的策略（草稿）')
  await loadMine()
}
async function toggleLike(s: WorkshopStrategy) {
  if (s.liked_by_me) await workshopApi.unlike(s.id)
  else await workshopApi.like(s.id)
  await loadPublic()
}

async function openVersions(s: WorkshopStrategy) {
  versionFor.value = s
  versions.value = await workshopApi.versions(s.id)
  versionsOpen.value = true
}
function restoreVersion(v: WorkshopVersion) {
  editingId.value = versionFor.value?.id ?? null
  detailMode.value = false
  changeNote.value = `恢复自 v${v.version}`
  fillForm(v.snapshot)
  versionsOpen.value = false
  editorOpen.value = true
}

function openRun(s: WorkshopStrategy) {
  runFor.value = s
  runForm.mode = 'simulation'
  runForm.start_date = ''
  runForm.end_date = ''
  runForm.initial_capital = 1000000
  runResult.value = null
  runOpen.value = true
}
async function doApply() {
  if (!runFor.value) return
  applying.value = true
  try {
    const body: any = { mode: runForm.mode }
    if (runForm.mode === 'simulation') {
      body.start_date = runForm.start_date || undefined
      body.end_date = runForm.end_date || undefined
      body.initial_capital = runForm.initial_capital
    }
    const res = await workshopApi.apply(runFor.value.id, body)
    runResult.value = res.result
    ElMessage.success('策略运行完成')
    await loadRuns()
    await nextTick()
    renderChart()
  } finally { applying.value = false }
}
function renderChart() {
  disposeChart()
  const curve = runResult.value?.nav_curve
  if (!navEl.value || !curve?.length) return
  navChart = echarts.init(navEl.value)
  navChart.setOption({
    animationDurationUpdate: 0,
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: curve.map((p: any) => p.date || '') },
    yAxis: { type: 'value', scale: true },
    tooltip: { trigger: 'axis' },
    series: [{ type: 'line', name: '策略净值', data: curve.map((p: any) => p.nav ?? p.value ?? p), showSymbol: false, lineStyle: { width: 2 } }],
  })
}
function disposeChart() { navChart?.dispose(); navChart = null }

onMounted(() => {
  loadMine()
  // 编辑器首次打开就要用到内置/自建算法选项，不能等到切到「我的算法」页签才加载
  loadAlgorithms()
})
onBeforeUnmount(disposeChart)
</script>

<style scoped>
.ws-page { padding: 20px; }
.ws-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.ws-head h2 { margin: 0 0 6px; font-size: 22px; display: flex; align-items: center; gap: 6px; }
.ws-head p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; max-width: 680px; line-height: 1.6; }
.ws-tabs { margin-top: 12px; }
.ws-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.ws-card, .ws-run-card { background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color-light); border-radius: 10px; padding: 16px; }
.ws-card-head { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
.ws-title-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ws-title-row h3 { margin: 0; font-size: 16px; }
.ws-version { color: var(--el-text-color-secondary); font-size: 12px; white-space: nowrap; }
.ws-desc { margin: 10px 0; font-size: 13px; color: var(--el-text-color-regular); min-height: 20px; line-height: 1.6; }
.ws-meta, .ws-run-summary { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 12px; color: var(--el-text-color-secondary); }
.ws-meta b, .ws-run-summary b { color: var(--el-text-color-primary); }
.ws-rule-summary { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0; min-height: 24px; }
.ws-chip { font-size: 11px; border-radius: 4px; padding: 3px 6px; background: var(--el-fill-color-light); color: var(--el-text-color-regular); }
.ws-chip-action { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.ws-card-actions { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--el-border-color-lighter); padding-top: 12px; }
.ws-action-primary { width: 100%; }
.ws-action-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.ws-action-grid-one { grid-template-columns: 1fr; }
.ws-action-grid .el-button { margin: 0; width: 100%; }
.ws-empty { padding: 40px; text-align: center; color: var(--el-text-color-secondary); background: var(--el-fill-color-lighter); border-radius: 10px; }
.ws-runs { display: flex; flex-direction: column; gap: 12px; }
.ws-run-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.ws-run-head strong { font-size: 15px; }
.ws-error { color: var(--el-color-danger); font-size: 13px; }
.ws-section-title { display: flex; justify-content: space-between; align-items: center; font-weight: 600; margin: 18px 0 6px; }
.ws-section-actions { display: flex; gap: 8px; align-items: center; }
.ws-condition-mode { display: flex; align-items: center; gap: 10px; margin: 4px 0 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.ws-conflict { margin: 6px 0 10px; }
.ws-algo-select { width: 150px; }
.ws-hint { margin: 0 0 10px; font-size: 12px; line-height: 1.6; color: var(--el-text-color-secondary); }
.ws-sort-hint { margin: 8px 0 0; }
.ws-rule-row { display: flex; gap: 8px; margin-bottom: 8px; }
.ws-field { width: 42%; }
.ws-op { width: 26%; }
.ws-value { flex: 1; min-width: 90px; }
.ws-risk-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 4px 12px; }
.ws-version-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.ws-version-row p { margin: 4px 0; font-size: 13px; }
.ws-version-row small { font-size: 11px; }
.ws-muted { color: var(--el-text-color-secondary); font-size: 12px; }
.ws-run-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 10px; }
.ws-metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; margin: 16px 0; }
.ws-metrics > div { background: var(--el-fill-color-lighter); border-radius: 8px; padding: 10px; }
.ws-metrics span { display: block; font-size: 12px; color: var(--el-text-color-secondary); }
.ws-metrics b { font-size: 16px; }
.ws-gain { color: var(--el-color-danger); }
.ws-loss { color: var(--el-color-success); }
.ws-nav-chart { width: 100%; height: 260px; }
.ws-signal-list h4 { margin: 16px 0 8px; font-size: 14px; }
.ws-signal-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); font-size: 13px; }
.ws-signal-row small { width: 100%; color: var(--el-text-color-secondary); }
@media (max-width: 768px) {
  .ws-page { padding: 12px; }
  .ws-head h2 { font-size: 17px; }
  .ws-grid { grid-template-columns: 1fr; }
  .ws-field { width: 38%; }
  .ws-op { width: 30%; }
  .ws-nav-chart { height: var(--chart-h-sm); }
}
</style>
