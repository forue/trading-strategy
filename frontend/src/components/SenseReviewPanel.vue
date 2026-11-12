<template>
  <div v-if="review" class="review-panel">
    <div class="review-title">
      <span>盘后总结 · 观察点与统计倾向</span>
      <div class="review-toggles">
        <el-switch
          :model-value="signalsOn"
          size="small"
          inline-prompt
          active-text="显示"
          inactive-text="隐藏"
          @change="onToggleSignals"
        />
        <span class="toggle-label">建议点</span>
        <el-switch
          v-model="showWatch"
          size="small"
          inline-prompt
          active-text="含中性"
          inactive-text="仅定向"
          :disabled="!signalsOn"
        />
      </div>
    </div>
    <p class="review-summary">{{ review.summary }}</p>

    <details v-if="review.method" class="review-method">
      <summary>统计口径与不确定性（建议先读）</summary>
      <p>{{ review.method }}</p>
    </details>

    <div v-if="shown.length" class="review-list">
      <div v-for="it in shown" :key="it.s.no + it.s.date" class="review-row" :class="it.s.action">
        <div class="row-head">
          <span class="review-no" :class="it.s.action">{{ it.label }}</span>
          <span class="review-date">{{ it.s.date }}</span>
          <span class="review-action" :class="it.s.action">{{ actionText(it.s.action) }}</span>
          <span class="review-meta">第{{ it.s.no }}根 · 收盘 {{ it.s.price.toFixed(3) }}</span>
          <b class="row-title">{{ it.s.title }}</b>
          <span v-if="it.s.action !== 'watch' && it.s.net !== undefined" class="review-score">
            {{ it.s.confidence || '' }}置信 · {{ signed(it.s.net) }}
          </span>
        </div>

        <div class="row-body">
          <div v-if="it.s.window?.length" class="window-box" @click="openWindow(it)">
            <SenseCandleDiagram :bars="it.s.window" :focus="it.s.focus" :width="132" :height="44" />
            <span>触发点及之前 8 根 · 点开对照</span>
          </div>
          <div class="reasons">
            <div v-for="(r, j) in it.s.reasons" :key="j" class="review-reason">
              <span class="reason-tag" :data-tag="r.tag">{{ r.tag }}</span>
              <span class="reason-text">{{ r.text }}</span>
              <el-link
                v-if="r.pattern && review.patterns?.[r.pattern]"
                type="primary"
                :underline="false"
                class="shape-link"
                @click="openShape(r.pattern!, it)"
              >
                图形示例
              </el-link>
              <span v-if="r.stat?.n" class="stat" :title="statTip(r)">
                样本 {{ r.stat.n }} · 后5日 {{ signed(r.stat.r5) }}% · 上涨 {{ r.stat.pos5 }}%
                <b v-if="r.contrarian" class="contrarian">与教科书相反</b>
                <b v-else-if="r.bias === 0" class="neutral">未定向</b>
              </span>
            </div>
          </div>
        </div>

        <div v-if="it.s.execute" class="row-foot">
          {{ it.s.execute }}执行 · 失效位 {{ it.s.invalidate }} · 观察 {{ it.s.horizon }} 个交易日
        </div>
      </div>
    </div>
    <div v-else class="empty-tip">
      {{
        signalsOn
          ? '本区间没有达到定向条件的参考点，打开「含中性」可看形态观察点'
          : '建议点已隐藏，复盘图只保留你自己的 B/S 买卖点；打开「建议点」即可恢复'
      }}
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="460px" append-to-body>
      <div v-if="activeShape" class="shape-box">
        <div class="shape-label">标准形态示意（{{ activeShape.name }}）</div>
        <SenseCandleDiagram :bars="activeShape.bars" :focus="activeShape.focus" :width="400" :height="130" />
        <p>{{ activeShape.note }}</p>
        <p v-if="activeShape.rule" class="shape-rule">
          命中条件：{{ activeShape.rule }}（量能与均线位置无法在K线图中画出）
        </p>
      </div>
      <div v-if="activeWindow.length" class="shape-box">
        <div class="shape-label">本轮实际走势（取与示意相同的最后 {{ activeWindow.length }} 根）</div>
        <SenseCandleDiagram :bars="activeWindow" :focus="activeWindow.length - 1" :width="400" :height="130" />
        <p>
          蓝色虚线标出触发那一根。两图根数一致、各自按自身价格区间归一化，便于逐根对照；
          真实命中常是教科书形态的变形，且量能/均线条件不看图判断。
        </p>
      </div>
      <div
        v-if="activeSignal?.window?.length && activeSignal.window.length > activeWindow.length"
        class="shape-box"
      >
        <div class="shape-label">完整局部走势（触发点及之前 8 根）</div>
        <SenseCandleDiagram :bars="activeSignal.window" :focus="activeSignal.focus" :width="400" :height="90" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import SenseCandleDiagram from './SenseCandleDiagram.vue'
import type {
  SensePatternShape,
  SenseReview,
  SenseReviewReason,
  SenseReviewSignal,
} from '@/api/stockSense'

const props = defineProps<{ review?: SenseReview | null; showSignals?: boolean }>()
const emit = defineEmits<{ 'update:showSignals': [value: boolean] }>()

/** 受控显示：结算弹窗、复盘抽屉与图上编号圆点共用一个开关状态 */
const signalsOn = computed(() => props.showSignals ?? true)
function onToggleSignals(v: unknown) {
  emit('update:showSignals', Boolean(v))
}

const showWatch = ref(false)
const directional = computed(() => (props.review?.signals || []).filter((s) => s.action !== 'watch'))
const shown = computed(() => {
  if (!signalsOn.value) return []
  const list = showWatch.value ? props.review?.signals || [] : directional.value
  return list.map((s) => ({
    s,
    label: s.action === 'watch'
      ? '·'
      : String(directional.value.findIndex((d) => d.no === s.no) + 1),
  }))
})

const dialogVisible = ref(false)
const dialogTitle = ref('')
const activeShape = ref<SensePatternShape | null>(null)
const activeSignal = ref<SenseReviewSignal | null>(null)
/** 与标准示意取相同根数，避免 9 根实际走势与 2~4 根示意同宽渲染造成视觉错位 */
const activeWindow = computed(() => {
  const w = activeSignal.value?.window || []
  const n = activeShape.value?.bars.length
  return n ? w.slice(-n) : w
})

function actionText(a: string) {
  return a === 'buy' ? '统计偏多' : a === 'sell' ? '统计偏空' : '中性观察'
}
function signed(v: number | undefined) {
  const n = v ?? 0
  return (n > 0 ? '+' : '') + n.toFixed(2)
}
function statTip(r: SenseReviewReason) {
  const s = r.stat
  if (!s) return ''
  const book = s.side > 0 ? '教科书看多' : '教科书看空'
  return `${book}；离线样本 ${s.n} 次，形态后 5 日平均 ${s.r5}%、上涨比例 ${s.pos5}%；` +
    `两组分别为 ${s.h0}% / ${s.h1}%（方向只由第一组确定，第二组不参与定向；下一交易日开盘介入、第 5 日收盘退出）`
}
function openShape(key: string, it: { s: SenseReviewSignal }) {
  const shape = props.review?.patterns?.[key]
  if (!shape) return
  activeShape.value = shape
  activeSignal.value = it.s
  dialogTitle.value = `${shape.name} · 图形示例`
  dialogVisible.value = true
}
function openWindow(it: { s: SenseReviewSignal }) {
  const usable = (x: SenseReviewReason) => x.pattern && props.review?.patterns?.[x.pattern]
  // 优先展示本行主形态的示意，而不是列表里第一条恰好有图的理由
  const r = it.s.reasons.find((x) => x.title === it.s.title && usable(x))
    || it.s.reasons.find(usable)
  if (r?.pattern) {
    openShape(r.pattern, it)
  } else {
    activeShape.value = null
    activeSignal.value = it.s
    dialogTitle.value = '本轮实际走势'
    dialogVisible.value = true
  }
}
</script>

<style scoped>
.review-panel {
  margin: 10px 0;
  padding: 10px 12px;
  border: 1px solid var(--border-primary, #e4e7ed);
  border-radius: 8px;
  background: var(--bg-secondary, #ffffff);
}

.review-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1a1d2e);
  margin-bottom: 6px;
}

.review-toggles {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 400;
}

.toggle-label {
  font-size: 11px;
  color: var(--text-secondary, #8a94a6);
}

.review-summary {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary, #8a94a6);
  margin: 0 0 8px;
}

.review-method {
  font-size: 11px;
  color: var(--text-tertiary, #9499a6);
  border: 1px dashed var(--border-primary, #e4e7ed);
  border-radius: 6px;
  padding: 4px 8px;
  margin-bottom: 8px;
}

.review-method summary {
  cursor: pointer;
  color: #409eff;
}

.review-method p {
  margin: 6px 0 2px;
  line-height: 1.7;
}

.review-list {
  max-height: 340px;
  overflow-y: auto;
}

.review-row {
  padding: 8px 0;
  border-top: 1px dashed var(--border-primary, #e4e7ed);
  font-size: 12px;
}

.row-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  line-height: 1.6;
}

.review-no {
  flex: none;
  min-width: 20px;
  height: 20px;
  line-height: 20px;
  padding: 0 4px;
  text-align: center;
  border-radius: 10px;
  color: #fff;
  font-size: 11px;
  background: #909399;
}

.review-no.buy {
  background: #d81e06;
}

.review-no.sell {
  background: #0a9b45;
}

.review-date {
  color: var(--text-primary, #1a1d2e);
  font-weight: 600;
}

.review-action {
  padding: 0 5px;
  border-radius: 3px;
  font-size: 11px;
  color: #fff;
  background: #909399;
}

.review-action.buy {
  background: #d81e06;
}

.review-action.sell {
  background: #0a9b45;
}

.review-meta {
  color: var(--text-tertiary, #9499a6);
  font-size: 11px;
}

.row-title {
  color: var(--text-primary, #1a1d2e);
}

.review-score {
  margin-left: auto;
  font-size: 11px;
  color: #b18cf0;
}

.row-body {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: 4px;
}

.window-box {
  flex: none;
  cursor: pointer;
  padding: 3px;
  border: 1px solid var(--border-primary, #e4e7ed);
  border-radius: 5px;
  text-align: center;
}

.window-box:hover {
  border-color: #409eff;
}

.window-box span {
  display: block;
  font-size: 9px;
  color: var(--text-tertiary, #9499a6);
  margin-top: 1px;
}

.reasons {
  flex: 1;
  min-width: 0;
}

.review-reason {
  line-height: 1.7;
  color: var(--text-secondary, #8a94a6);
}

.reason-tag {
  display: inline-block;
  margin-right: 6px;
  padding: 0 4px;
  border: 1px solid #b18cf0;
  border-radius: 3px;
  color: #b18cf0;
  font-size: 10px;
}

.reason-tag[data-tag='出货'],
.reason-tag[data-tag='背离'] {
  border-color: #e6a23c;
  color: #e6a23c;
}

.reason-tag[data-tag='洗盘'] {
  border-color: #67c23a;
  color: #67c23a;
}

.shape-link {
  margin-left: 6px;
  font-size: 11px;
  vertical-align: baseline;
}

.stat {
  display: inline-block;
  margin-left: 6px;
  font-size: 10px;
  color: var(--text-tertiary, #9499a6);
}

.contrarian {
  margin-left: 4px;
  color: #e6a23c;
}

.neutral {
  margin-left: 4px;
  color: #909399;
}

.row-foot {
  margin-top: 4px;
  font-size: 11px;
  color: #409eff;
}

.shape-box {
  margin-bottom: 12px;
}

.shape-label {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 4px;
}

.shape-box p {
  font-size: 11px;
  line-height: 1.7;
  color: var(--text-secondary, #8a94a6);
  margin: 6px 0 0;
}

.shape-rule {
  color: #409eff;
}
</style>
