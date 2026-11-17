/** 统一的 HTTP 客户端：服务地址 + Bearer 令牌 + 错误分类。
 *
 * 错误分类直接对应 README 里要求区分的四种失败：
 * - network：端口不通 / DNS 解析失败
 * - cert：HTTPS 证书不被信任
 * - auth：401 令牌失效（全局跳绑定页）
 * - rate：429 限流
 */

export type FailureKind = 'network' | 'cert' | 'auth' | 'rate' | 'http' | 'server'

export class ApiFailure extends Error {
  kind: FailureKind
  code: string
  status: number
  details?: unknown

  constructor(kind: FailureKind, message: string, code = '', status = 0, details?: unknown) {
    super(message)
    this.kind = kind
    this.code = code
    this.status = status
    this.details = details
  }
}

const TOKEN_KEY = 'study.token'
const SERVER_KEY = 'study.server'

let unauthorizedHandler: (() => void) | null = null
export function onUnauthorized(handler: () => void) {
  unauthorizedHandler = handler
}

export function getServer(): string {
  return localStorage.getItem(SERVER_KEY) || ''
}
export function setServer(value: string) {
  const trimmed = value.trim().replace(/\/+$/, '')
  if (trimmed) localStorage.setItem(SERVER_KEY, trimmed)
  else localStorage.removeItem(SERVER_KEY)
}
export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(value: string) {
  if (value) localStorage.setItem(TOKEN_KEY, value)
  else localStorage.removeItem(TOKEN_KEY)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

/** 服务地址为空时走同源（插件托管 /study/ 的场景）。 */
function baseUrl(): string {
  return getServer()
}

async function parse(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export async function request<T = any>(
  method: string,
  path: string,
  body?: unknown,
  options: { auth?: boolean; timeoutMs?: number; raw?: boolean } = {},
): Promise<T> {
  const { auth = true, timeoutMs = 60_000 } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  // 旧 WebView（Chrome < 66）没有 AbortController，直接 new 会抛 "AbortController is not defined"，
  // 于是所有接口都失败、界面看起来像坏的。没有它就退回 Promise.race 超时（只是不能真正取消请求）。
  const canAbort = typeof AbortController === 'function'
  const controller = canAbort ? new AbortController() : null
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    if (controller) controller.abort()
  }, timeoutMs)
  const url = `${baseUrl()}/api/study${path}`
  const init: RequestInit = {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  }
  if (controller) init.signal = controller.signal
  let response: Response
  try {
    response = controller
      ? await fetch(url, init)
      : await Promise.race([
          fetch(url, init),
          new Promise<Response>((_, reject) => {
            setTimeout(() => reject(new Error('timeout')), timeoutMs)
          }),
        ])
  } catch (error: any) {
    const message = String(error?.message || error)
    if (timedOut || message === 'timeout') {
      throw new ApiFailure('network', '服务没有响应：检查地址、端口与防火墙，或这台机器太慢')
    }
    if (/certificate|SSL|TLS/i.test(message)) {
      throw new ApiFailure('cert', 'HTTPS 证书不被信任：请换用受信任证书，或在系统中信任该证书')
    }
    throw new ApiFailure('network', '连接不上服务：请检查地址、端口、防火墙与是否同一局域网')
  } finally {
    clearTimeout(timer)
  }

  const payload: any = await parse(response)
  if (response.status === 401) {
    clearToken()
    unauthorizedHandler?.()
    throw new ApiFailure('auth', '令牌已失效，请重新绑定', 'UNAUTHORIZED', 401)
  }
  if (response.status === 429) {
    throw new ApiFailure('rate', '请求过于频繁，请稍后再试', 'RATE_LIMITED', 429)
  }
  if (!response.ok) {
    const error = payload?.error || {}
    throw new ApiFailure(
      response.status >= 500 ? 'server' : 'http',
      error.message || `请求失败（HTTP ${response.status}）`,
      error.code || 'INTERNAL',
      response.status,
      error.details,
    )
  }
  if (payload && typeof payload === 'object' && 'ok' in payload) {
    if (payload.ok === false) {
      const error = payload.error || {}
      throw new ApiFailure('http', error.message || '请求失败', error.code || 'INTERNAL', response.status)
    }
    return payload.data as T
  }
  return payload as T
}

export const api = {
  get: <T = any>(path: string, options?: any) => request<T>('GET', path, undefined, options),
  post: <T = any>(path: string, body?: unknown, options?: any) =>
    request<T>('POST', path, body, options),
  put: <T = any>(path: string, body?: unknown, options?: any) =>
    request<T>('PUT', path, body, options),
  patch: <T = any>(path: string, body?: unknown, options?: any) =>
    request<T>('PATCH', path, body, options),
  del: <T = any>(path: string, options?: any) => request<T>('DELETE', path, undefined, options),
}

/** 绑定流程用：不需要令牌。 */
export async function createBindCode() {
  return request<{ code: string; expires_in: number; instruction: string }>(
    'POST',
    '/auth/bind-code',
    {},
    { auth: false },
  )
}

export async function bindStatus(code: string) {
  return request<{ bound: boolean }>('GET', `/auth/bind-status?code=${encodeURIComponent(code)}`, undefined, {
    auth: false,
  })
}

export async function exchangeToken(code: string) {
  return request<{ token: string; principal: any; device_count: number }>(
    'POST',
    '/auth/token',
    { code, label: deviceLabel() },
    { auth: false },
  )
}

function deviceLabel(): string {
  const ua = navigator.userAgent
  if (/Android/i.test(ua)) return 'Android'
  if (/Windows/i.test(ua)) return 'Windows'
  if (/iPhone|iPad/i.test(ua)) return 'iOS'
  if (/Mac/i.test(ua)) return 'macOS'
  return 'Web'
}

export function humanError(error: unknown): string {
  if (error instanceof ApiFailure) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}
