import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import {
  DataBoard, Setting, Bell, Wallet, Monitor, VideoPlay, Tools,
  TrendCharts, DataLine, User, Lock, ArrowDown, Refresh,
  Search, Plus, Edit, Delete, View, Download, Upload,
  Check, Close, Warning, InfoFilled, SuccessFilled,
  Menu, HomeFilled, Operation, Histogram, PieChart,
} from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import './styles/index.scss'

const app = createApp(App)

// 按需注册图标（替代全量导入，减少打包体积）
const icons = {
  DataBoard, Setting, Bell, Wallet, Monitor, VideoPlay, Tools,
  TrendCharts, DataLine, User, Lock, ArrowDown, Refresh,
  Search, Plus, Edit, Delete, View, Download, Upload,
  Check, Close, Warning, InfoFilled, SuccessFilled,
  Menu, HomeFilled, Operation, Histogram, PieChart,
}
for (const [key, component] of Object.entries(icons)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
