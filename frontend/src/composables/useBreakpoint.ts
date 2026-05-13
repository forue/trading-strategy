import { ref, onMounted, onUnmounted } from 'vue'

export function useBreakpoint() {
  const width = ref(window.innerWidth)
  const isMobile = ref(window.innerWidth < 480)
  const isTablet = ref(window.innerWidth < 768)
  const isDesktop = ref(window.innerWidth >= 1024)

  let timer: ReturnType<typeof setTimeout> | null = null
  function onResize() {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      width.value = window.innerWidth
      isMobile.value = window.innerWidth < 480
      isTablet.value = window.innerWidth < 768
      isDesktop.value = window.innerWidth >= 1024
    }, 100)
  }

  onMounted(() => window.addEventListener('resize', onResize))
  onUnmounted(() => {
    window.removeEventListener('resize', onResize)
    if (timer) clearTimeout(timer)
  })

  // Return how many x-axis labels to show for a given dataset size
  function labelCount(dataLength: number, minLabels = 5): number {
    if (isMobile.value) return Math.max(minLabels, Math.min(dataLength, 8))
    if (isTablet.value) return Math.max(minLabels, Math.min(dataLength, 14))
    return dataLength
  }

  // Return label interval (every Nth label)
  function labelInterval(dataLength: number): number {
    return Math.max(1, Math.floor(dataLength / labelCount(dataLength)))
  }

  return { width, isMobile, isTablet, isDesktop, labelCount, labelInterval }
}
