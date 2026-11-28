import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { VitePWA } from 'vite-plugin-pwa'
import { createHash } from 'crypto'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// Windows / Chrome 会按完整 URL 缓存已安装 PWA 的图标，固定 URL 换内容不会生效。
// 用图标文件的内容哈希做版本参数，图标一改 URL 就变，旧缓存自然失效。
const ICON_FILES = [
  'public/favicon.ico',
  'public/brand/rs-mark.svg',
  'public/brand/rs-mark-dark.svg',
  'public/brand/rs-mark-16.png',
  'public/brand/rs-mark-32.png',
  'public/brand/rs-mark-48.png',
  'public/brand/rs-mark-192.png',
  'public/brand/rs-mark-512.png',
]
const brandVersion = createHash('sha256')
  .update(ICON_FILES.map((f) => readFileSync(resolve(__dirname, f))).reduce((a, b) => Buffer.concat([a, b]), Buffer.alloc(0)))
  .digest('hex')
  .slice(0, 8)
const brandUrl = (path: string) => `/${path}?v=${brandVersion}`

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia'],
      dts: 'src/auto-imports.d.ts',
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts',
    }),
    {
      name: 'brand-icon-version',
      transformIndexHtml(html: string) {
        return html.replace(/(href="\/)(favicon\.ico|brand\/rs-mark[^"]*)(")/g,
          (_m, prefix: string, file: string, suffix: string) => `${prefix}${file}?v=${brandVersion}${suffix}`)
      },
    },
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'pwa-192x192.svg', 'pwa-512x512.svg', 'brand/rs-mark.svg', 'brand/rs-mark-dark.svg', 'brand/rs-mark-16.png', 'brand/rs-mark-32.png', 'brand/rs-mark-48.png', 'brand/rs-mark-192.png', 'brand/rs-mark-512.png'],
      manifest: {
        name: '轮动策略交易系统',
        short_name: '轮动策略',
        description: '板块轮动策略交易系统 - 激进/稳健/保守三种策略',
        theme_color: '#4051E0',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        scope: '/',
        start_url: '/',
        icons: [
          { src: brandUrl('brand/rs-mark.svg').slice(1), sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
          { src: brandUrl('brand/rs-mark-192.png').slice(1), sizes: '192x192', type: 'image/png' },
          { src: brandUrl('brand/rs-mark-512.png').slice(1), sizes: '512x512', type: 'image/png' }
        ]
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg}'],
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-cache',
              expiration: {
                maxEntries: 10,
                maxAgeSeconds: 60 * 60 * 24 * 365
              },
              cacheableResponse: {
                statuses: [0, 200]
              }
            }
          },
          {
            urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'gstatic-fonts-cache',
              expiration: {
                maxEntries: 10,
                maxAgeSeconds: 60 * 60 * 24 * 365
              },
              cacheableResponse: {
                statuses: [0, 200]
              }
            }
          }
        ]
      }
    })
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api/auth': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/strategy': {
        target: 'http://localhost:8002',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/strategy/, ''),
      },
      '/api/data': {
        target: 'http://localhost:8003',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/data/, ''),
      },
      '/api/signals': {
        target: 'http://localhost:8004',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/signals/, '/signals'),
      },
      '/api/fund': {
        target: 'http://localhost:8005',
        changeOrigin: true,
      },
      '/api/scheduler': {
        target: 'http://localhost:8006',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/scheduler/, ''),
      },
      '/api/ai': {
        target: 'http://localhost:8007',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8004',
        ws: true,
      },
    },
  },
})
