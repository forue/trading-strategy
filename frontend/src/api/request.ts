import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const request = axios.create({
  baseURL: '/api',
  timeout: 300000,  // 5分钟超时用于自动寻优
})

// 请求拦截器 - 自动携带Token
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器 - 统一错误处理
request.interceptors.response.use(
  (response) => {
    const { code, message, data } = response.data
    if (code === 200 || code === 0) {
      // 需要读取 data 之外的元信息（如 position_status）时，请求可声明 X-Raw-Response
      if ((response.config as any)?.['X-Raw-Response']) {
        return response.data
      }
      return data
    }
    if (!response.config?.headers?.['X-Silent']) {
      ElMessage.error(message || '请求失败')
    }
    return Promise.reject(new Error(message))
  },
  (error) => {
    const silent = error.config?.headers?.['X-Silent']
    if (error.response?.status === 401 || error.response?.status === 403) {
      localStorage.removeItem('token')
      router.push('/login')
      ElMessage.error('登录已过期，请重新登录')
    } else if (!silent) {
      // 区分「服务端错误」与「真正的网络失败」：
      // Spring 默认 500 响应体只有 {timestamp,status,error,path}，没有 message，
      // 若直接兜底成「网络错误」会把后端异常误报成网络问题。
      const data = error.response?.data
      const serverMsg = data?.message || data?.error
      if (serverMsg) {
        ElMessage.error(serverMsg)
      } else if (error.response) {
        ElMessage.error(`请求失败(${error.response.status})：${error.response.statusText || '服务端异常'}`)
      } else {
        ElMessage.error('网络错误：服务未响应，请检查网络或服务状态')
      }
    }
    return Promise.reject(error)
  }
)

export default request
