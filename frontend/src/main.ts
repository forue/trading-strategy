import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import {
  DataBoard, Setting, Bell, Wallet, Monitor, VideoPlay, Tools,
  TrendCharts, DataLine, User, Lock, ArrowDown, Refresh,
  Search, Plus, Edit, Delete, View, Download, Upload,
  Check, Close, Warning, InfoFilled, SuccessFilled,
  Menu, HomeFilled, Operation, Histogram, PieChart,
  Sunny, Moon,
} from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import './styles/index.scss'

const app = createApp(App)

const icons = {
  DataBoard, Setting, Bell, Wallet, Monitor, VideoPlay, Tools,
  TrendCharts, DataLine, User, Lock, ArrowDown, Refresh,
  Search, Plus, Edit, Delete, View, Download, Upload,
  Check, Close, Warning, InfoFilled, SuccessFilled,
  Menu, HomeFilled, Operation, Histogram, PieChart,
  Sunny, Moon,
}
for (const [key, component] of Object.entries(icons)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
