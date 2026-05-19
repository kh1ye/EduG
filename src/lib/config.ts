/**
 * 应用配置
 * 统一管理所有配置项
 */

import { cache, CacheConfigs, generateCacheKey } from './cache'

export const config = {
  // API 基础地址
  apiBaseUrl: process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000',  // 后端在8000端口

  // 文件上传
  maxFileSize: 50 * 1024 * 1024, // 50MB

  // Token 配置
  tokenExpireMinutes: 120, // 2 小时

  // 分页配置
  defaultPageSize: 20,

  // 章节解锁阈值
  unlockThreshold: {
    completion: 0.7,      // 70% 完成度
    quizScore: 0.6,       // 60% 测试分数
    minTimeMinutes: 10    // 最少 10 分钟学习时间
  }
}

/**
 * 获取完整的 API URL
 */
export function getApiUrl(path: string): string {
  const baseUrl = config.apiBaseUrl.replace(/\/$/, '') // 移除尾部斜杠
  const apiPath = path.startsWith('/') ? path : `/${path}`
  return `${baseUrl}${apiPath}`
}

/**
 * 带超时的 fetch 包装器
 * 防止请求无限期等待导致 UI 阻塞
 */
export async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeout: number = 10000
): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal
    })
    clearTimeout(timeoutId)
    return response
  } catch (error) {
    clearTimeout(timeoutId)
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`请求超时 (${timeout / 1000}秒)`)
    }
    throw error
  }
}

/**
 * 🔧 获取认证头（简化版 - 从 localStorage 读取）
 */
export function getAuthHeadersSimple(includeContentType: boolean = true): HeadersInit {
  const headers: Record<string, string> = {}

  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('token')
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
      console.log('🔑 发送认证头，token 长度:', token.length)
    } else {
      console.warn('⚠️ 没有 token，请先登录')
    }
  }

  if (includeContentType) {
    headers['Content-Type'] = 'application/json'
  }

  return headers as HeadersInit
}

export async function refreshAccessToken(): Promise<boolean> {
  if (typeof window === 'undefined') {
    return false
  }

  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) {
    return false
  }

  try {
    const response = await fetch(getApiUrl('/api/users/refresh-token'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken })
    })

    if (!response.ok) {
      return false
    }

    const data = await response.json()
    if (!data.access_token) {
      return false
    }

    localStorage.setItem('token', data.access_token)
    if (data.refresh_token) {
      localStorage.setItem('refresh_token', data.refresh_token)
    }

    return true
  } catch (error) {
    console.error('刷新 token 失败:', error)
    return false
  }
}

export async function fetchWithAuthRetry(
  url: string,
  options: RequestInit = {},
  timeout: number = 10000,
  includeContentType: boolean = true
): Promise<Response> {
  const buildOptions = (): RequestInit => ({
    ...options,
    headers: {
      ...getAuthHeadersSimple(includeContentType),
      ...(options.headers || {})
    }
  })

  let response = await fetchWithTimeout(url, buildOptions(), timeout)
  if (response.status === 401 && await refreshAccessToken()) {
    response = await fetchWithTimeout(url, buildOptions(), timeout)
  }

  return response
}

/**
 * 带缓存的 fetch 函数
 * 自动缓存 GET 请求的响应
 */
export async function fetchWithCache<T>(
  url: string,
  options: RequestInit = {},
  cacheKey?: string,
  cacheConfig?: CacheConfig
): Promise<T> {
  // 只缓存 GET 请求
  const isGetRequest = !options.method || options.method.toUpperCase() === 'GET'

  if (isGetRequest) {
    const key = cacheKey || url
    const cached = cache.get<T>(key)
    if (cached !== null) {
      console.log(`[Cache] 命中缓存: ${key}`)
      return cached
    }
  }

  // 发起请求
  const response = await fetchWithTimeout(url, options)

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  const data = await response.json()

  // 缓存 GET 请求的响应
  if (isGetRequest) {
    const key = cacheKey || url
    const config = cacheConfig || CacheConfigs.documents
    cache.set(key, data, config)
    console.log(`[Cache] 已缓存: ${key}`)
  }

  return data
}

interface CacheConfig {
  ttl?: number
  persistent?: boolean
}
