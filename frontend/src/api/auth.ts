import request from './request'

export interface UserInfo {
  id: number
  username: string
  email: string
  role: string
}

export interface LoginParams {
  username: string
  password: string
}

export interface LoginResult {
  token: string
  user: UserInfo
}

export const authApi = {
  login(params: LoginParams): Promise<LoginResult> {
    return request.post('/auth/login', params)
  },

  register(params: { username: string; password: string; email: string }): Promise<LoginResult> {
    return request.post('/auth/register', params)
  },

  getUserInfo(): Promise<UserInfo> {
    return request.get('/auth/user/info')
  },

  logout(): Promise<void> {
    return request.post('/auth/logout')
  },
}
