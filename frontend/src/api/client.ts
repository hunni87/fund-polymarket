import type {
  Decision,
  Fund,
  Market,
  MarketCreate,
  MarketDetail,
  Member,
  Order,
  OrderSyncResult,
  Outcome,
  Quote,
  Score,
  Symbol,
  SystemStatus,
} from './types'

const TOKEN_KEY = 'fund-polymarket.token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`/api/v1${path}`, { ...init, headers })

  if (res.status === 401) {
    setToken(null)
    throw new ApiError(401, '로그인이 필요합니다.')
  }

  if (!res.ok) {
    let detail = `요청이 실패했습니다 (${res.status})`
    let code: string | undefined
    try {
      const body = await res.json()
      code = body.code
      // FastAPI 검증 오류는 detail이 배열로 온다.
      detail = Array.isArray(body.detail)
        ? body.detail.map((d: { msg: string }) => d.msg).join(', ')
        : (body.detail ?? detail)
    } catch {
      /* 본문이 JSON이 아니면 기본 메시지를 쓴다 */
    }
    throw new ApiError(res.status, detail, code)
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  async login(email: string, password: string): Promise<void> {
    const body = new URLSearchParams({ username: email, password })
    const res = await fetch('/api/v1/auth/login', { method: 'POST', body })
    if (!res.ok) {
      throw new ApiError(res.status, '이메일 또는 비밀번호가 올바르지 않습니다.')
    }
    const data = (await res.json()) as { access_token: string }
    setToken(data.access_token)
  },

  logout(): void {
    setToken(null)
  },

  me: () => request<Member>('/auth/me'),
  members: () => request<Member[]>('/members'),
  leaderboard: () => request<Score[]>('/leaderboard'),
  systemStatus: () => request<SystemStatus>('/system/status'),

  funds: () => request<Fund[]>('/funds'),
  positions: (fundId: number) => request<unknown[]>(`/funds/${fundId}/positions`),

  searchSymbols: (q: string) =>
    request<Symbol[]>(`/symbols?q=${encodeURIComponent(q)}`),
  quoteSymbol: (ticker: string) => request<Quote>(`/symbols/${ticker}/quote`),

  createMarket: (payload: MarketCreate) =>
    request<Market>('/markets', { method: 'POST', body: JSON.stringify(payload) }),

  markets: (status?: string) =>
    request<Market[]>(`/markets${status ? `?status=${status}` : ''}`),
  market: (id: number) => request<MarketDetail>(`/markets/${id}`),

  allocate: (id: number, allocation: Partial<Record<Outcome, string>>, rationale?: string) =>
    request<unknown>(`/markets/${id}/allocation`, {
      method: 'PUT',
      body: JSON.stringify({ allocation, rationale: rationale || null }),
    }),

  closeMarket: (id: number) => request<Market>(`/markets/${id}/close`, { method: 'POST' }),
  buildDecision: (id: number) => request<Decision>(`/markets/${id}/decision`, { method: 'POST' }),
  decision: (id: number) => request<Decision>(`/markets/${id}/decision`),
  resolveMarket: (id: number) => request<Market>(`/markets/${id}/resolve`, { method: 'POST' }),
  settleMarket: (id: number) => request<Market>(`/markets/${id}/settle`, { method: 'POST' }),

  approveDecision: (id: number) =>
    request<Order>(`/decisions/${id}/approve`, { method: 'POST' }),
  rejectDecision: (id: number, reason: string) =>
    request<Decision>(`/decisions/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  orders: () => request<Order[]>('/orders'),
  syncOrders: () => request<OrderSyncResult>('/orders/sync', { method: 'POST' }),
}
