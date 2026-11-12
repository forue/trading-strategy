<template>
  <svg
    class="candle-diagram"
    :viewBox="`0 0 ${width} ${height}`"
    :width="width"
    :height="height"
    role="img"
    aria-label="K线形态示意图"
  >
    <line
      v-for="(g, i) in geo"
      :key="`w${i}`"
      :x1="g.x"
      :x2="g.x"
      :y1="g.highY"
      :y2="g.lowY"
      :stroke="g.color"
      stroke-width="1"
    />
    <rect
      v-for="(g, i) in geo"
      :key="`b${i}`"
      :x="g.x - g.bw / 2"
      :y="g.bodyY"
      :width="g.bw"
      :height="g.bodyH"
      :fill="g.color"
      :stroke="i === focus ? '#409eff' : 'none'"
      :stroke-width="i === focus ? 1.5 : 0"
    />
    <line
      v-if="marker && focus !== undefined && focus >= 0 && focus < geo.length"
      :x1="geo[focus].x"
      :x2="geo[focus].x"
      y1="0"
      :y2="height"
      stroke="#409eff"
      stroke-width="1"
      stroke-dasharray="3 3"
      opacity="0.6"
    />
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

type Candle = [number, number, number, number] | { o: number; h: number; l: number; c: number }

const props = withDefaults(defineProps<{
  bars: Candle[]
  /** 需要高亮的那一根（触发点或形态主体） */
  focus?: number
  width?: number
  height?: number
  marker?: boolean
}>(), { width: 160, height: 56, marker: true })

const candles = computed<[number, number, number, number][]>(() =>
  props.bars.map((b) => (Array.isArray(b) ? b : [b.o, b.h, b.l, b.c])),
)

const geo = computed(() => {
  const list = candles.value
  if (!list.length) return []
  const hi = Math.max(...list.map((c) => c[1]))
  const lo = Math.min(...list.map((c) => c[2]))
  const span = hi - lo || 1
  const pad = 4
  const usable = props.height - pad * 2
  const step = props.width / Math.max(list.length, 1)
  const bw = Math.max(2, Math.min(step * 0.6, 14))
  const y = (v: number) => pad + (hi - v) / span * usable
  return list.map((c, i) => {
    const top = y(Math.max(c[0], c[3]))
    const bottom = y(Math.min(c[0], c[3]))
    return {
      x: step * (i + 0.5),
      bw,
      highY: y(c[1]),
      lowY: y(c[2]),
      bodyY: top,
      bodyH: Math.max(1.5, bottom - top),
      color: c[3] >= c[0] ? '#ef232a' : '#14b143',
    }
  })
})
</script>

<style scoped>
.candle-diagram {
  display: block;
  flex: none;
}
</style>
