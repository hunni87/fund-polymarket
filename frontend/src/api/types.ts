export type Outcome = 'BUY' | 'SELL' | 'HOLD'

export const OUTCOMES: Outcome[] = ['BUY', 'SELL', 'HOLD']

export const OUTCOME_LABEL: Record<Outcome, string> = {
  BUY: '매수',
  SELL: '매도',
  HOLD: '홀딩',
}

export type MarketStatus =
  | 'OPEN'
  | 'CLOSED'
  | 'DECIDED'
  | 'EXECUTED'
  | 'RESOLVED'
  | 'SETTLED'
  | 'CANCELLED'

export const STATUS_LABEL: Record<MarketStatus, string> = {
  OPEN: '베팅 중',
  CLOSED: '마감',
  DECIDED: '결정 완료',
  EXECUTED: '주문 집행',
  RESOLVED: '판정 완료',
  SETTLED: '정산 완료',
  CANCELLED: '취소',
}

export interface Member {
  id: number
  email: string
  name: string
  role: string
  is_active: boolean
  created_at: string
  balance: string
}

export interface Fund {
  id: number
  name: string
  broker: string
  account_no: string
  base_currency: string
  is_active: boolean
}

export interface Consensus {
  probabilities: Record<string, number>
  stake_by_outcome: Record<string, string>
  total_stake: string
  participant_count: number
  leading_outcome: Outcome | null
}

export interface Market {
  id: number
  fund_id: number
  title: string
  description: string | null
  ticker: string
  ticker_name: string | null
  status: MarketStatus
  closes_at: string
  resolve_at: string
  buy_threshold_pct: string
  sell_threshold_pct: string
  reference_price: string | null
  resolution_price: string | null
  winning_outcome: Outcome | null
  notional_krw: string
  created_at: string
}

export interface Bet {
  id: number
  member_id: number
  outcome: Outcome
  stake: string
  rationale: string | null
  payout: string | null
  created_at: string
}

export interface MarketDetail extends Market {
  consensus: Consensus
  my_allocation: Record<string, string>
  bets: Bet[]
}

export interface Decision {
  id: number
  market_id: number
  action: Outcome
  probabilities: Record<string, number>
  total_stake: string
  participant_count: number
  target_quantity: number
  limit_price: string | null
  order_type: string
  status: string
  reason: string | null
  approved_by: number | null
  approved_at: string | null
  created_at: string
}

export interface Order {
  id: number
  market_id: number | null
  decision_id: number | null
  ticker: string
  side: string
  order_type: string
  quantity: number
  price: string | null
  broker_env: string
  broker_order_no: string | null
  status: string
  filled_quantity: number
  filled_avg_price: string | null
  error_message: string | null
  created_at: string
}

export interface Score {
  member_id: number
  name: string
  balance: string
  net_profit: string
  settled_markets: number
  hits: number
  hit_rate: string
  brier: string | null
}

export interface SystemStatus {
  broker_backend: string
  kis_env: string
  live_trading_enabled: boolean
  kill_switch: boolean
  max_order_amount_krw: string
  max_daily_orders: number
  execution_min_probability: string
  quorum_ratio: string
}
