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
      ElMessage.error(error.response?.data?.message || '网络错误')
    }
    return Promise.reject(error)
  }
)

export default request
