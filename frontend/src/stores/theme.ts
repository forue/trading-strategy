import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY = 'app-theme'

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(loadTheme())

  function loadTheme(): ThemeMode {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'dark' || saved === 'light') return saved
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }

  function applyTheme(m: ThemeMode) {
    const html = document.documentElement
    // Suppress all CSS transitions during theme switch to avoid
    // thousands of elements animating at different speeds ("lag")
    html.classList.add('theme-switching')
    html.classList.toggle('dark', m === 'dark')
    html.setAttribute('data-theme', m)
    // Restore transitions after the frame commits
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        html.classList.remove('theme-switching')
      })
    })
  }

  function toggle() {
    mode.value = mode.value === 'light' ? 'dark' : 'light'
  }

  function setTheme(m: ThemeMode) {
    mode.value = m
  }

  // Initial apply + watch
  applyTheme(mode.value)

  watch(mode, (m) => {
    localStorage.setItem(STORAGE_KEY, m)
    applyTheme(m)
  })

  return { mode, toggle, setTheme }
})
