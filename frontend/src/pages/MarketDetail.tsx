import { Fragment, useCallback, useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'

import { ApiError, api } from '../api/client'
import {
  OUTCOMES,
  OUTCOME_LABEL,
  STATUS_LABEL,
  type Decision,
  type MarketDetail,
  type Outcome,
} from '../api/types'
import { OddsBar } from '../components/OddsBar'
import { useAuth } from '../lib/auth'
import { datetime, krw, points, timeLeft } from '../lib/format'

type Allocation = Record<Outcome, string>

function AllocationForm({
  market,
  onDone,
}: {
  market: MarketDetail
  onDone: () => void
}) {
  const [alloc, setAlloc] = useState<Allocation>(() => ({
    BUY: market.my_allocation.BUY ?? '',
    SELL: market.my_allocation.SELL ?? '',
    HOLD: market.my_allocation.HOLD ?? '',
  }))
  const [rationale, setRationale] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [okMessage, setOkMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const total = OUTCOMES.reduce((sum, o) => sum + (Number(alloc[o]) || 0), 0)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setOkMessage(null)
    try {
      const payload: Partial<Record<Outcome, string>> = {}
      for (const o of OUTCOMES) {
        const n = Number(alloc[o])
        if (n > 0) payload[o] = String(n)
      }
      await api.allocate(market.id, payload, rationale)
      setOkMessage('제출했습니다. 마감 전까지 언제든 다시 낼 수 있습니다.')
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '제출에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={onSubmit}>
      <h3>내 의견</h3>
      <p className="muted">
        확신하는 만큼 포인트를 거세요. 한 쪽에 몰아도 되고, 나눠 걸어도 됩니다.
      </p>
      <div className="alloc-grid">
        {OUTCOMES.map((o) => (
          <Fragment key={o}>
            <span className={`badge ${o}`}>{OUTCOME_LABEL[o]}</span>
            <input
              type="number"
              min="0"
              step="1"
              placeholder="0"
              value={alloc[o]}
              onChange={(e) => setAlloc({ ...alloc, [o]: e.target.value })}
            />
          </Fragment>
        ))}
      </div>
      <textarea
        rows={2}
        placeholder="판단 근거 (선택) — 스터디 기록으로 남습니다"
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
      />
      <div className="row" style={{ marginTop: 12 }}>
        <span className="muted">합계 {points(total)}p</span>
        <div className="spacer" style={{ flex: 1 }} />
        <button type="submit" disabled={busy || total <= 0}>
          {busy ? '제출 중…' : '제출'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {okMessage && <p className="success">{okMessage}</p>}
    </form>
  )
}

function AdminPanel({
  market,
  decision,
  onChange,
}: {
  market: MarketDetail
  decision: Decision | null
  onChange: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      onChange()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '작업에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h3>운영자 액션</h3>
      <div className="row">
        {market.status === 'OPEN' && (
          <button
            className="secondary"
            disabled={busy}
            onClick={() => run(() => api.closeMarket(market.id))}
          >
            베팅 마감
          </button>
        )}
        {market.status === 'CLOSED' && (
          <button
            className="secondary"
            disabled={busy}
            onClick={() => run(() => api.buildDecision(market.id))}
          >
            매매 결정 산출
          </button>
        )}
        {decision?.status === 'PENDING_APPROVAL' && (
          <>
            <button disabled={busy} onClick={() => run(() => api.approveDecision(decision.id))}>
              주문 승인 · 집행
            </button>
            <button
              className="danger"
              disabled={busy}
              onClick={() => {
                const reason = window.prompt('반려 사유를 입력하세요')
                if (reason) void run(() => api.rejectDecision(decision.id, reason))
              }}
            >
              반려
            </button>
          </>
        )}
        {['CLOSED', 'DECIDED', 'EXECUTED'].includes(market.status) && (
          <button
            className="secondary"
            disabled={busy}
            onClick={() => run(() => api.resolveMarket(market.id))}
          >
            판정
          </button>
        )}
        {market.status === 'RESOLVED' && (
          <button disabled={busy} onClick={() => run(() => api.settleMarket(market.id))}>
            포인트 정산
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function DecisionCard({ decision }: { decision: Decision }) {
  return (
    <div className="card">
      <div className="row">
        <h3 style={{ flex: 1 }}>매매 결정</h3>
        <span className={`badge ${decision.action}`}>{OUTCOME_LABEL[decision.action]}</span>
        <span className="badge">{decision.status}</span>
      </div>
      {decision.status === 'SKIPPED' || decision.status === 'REJECTED' ? (
        <p className="muted">{decision.reason}</p>
      ) : (
        <p className="muted">
          {decision.target_quantity}주 · 지정가 {krw(decision.limit_price)}원 · 참여{' '}
          {decision.participant_count}명 · 총 스테이크 {points(decision.total_stake)}p
        </p>
      )}
      {decision.reason && decision.status === 'FAILED' && (
        <p className="error">{decision.reason}</p>
      )}
    </div>
  )
}

export function MarketDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { member } = useAuth()
  const marketId = Number(id)

  const [market, setMarket] = useState<MarketDetail | null>(null)
  const [decision, setDecision] = useState<Decision | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const detail = await api.market(marketId)
      setMarket(detail)
      try {
        setDecision(await api.decision(marketId))
      } catch {
        setDecision(null) // 아직 결정이 없는 것은 오류가 아니다
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '불러오지 못했습니다.')
    }
  }, [marketId])

  useEffect(() => {
    void load()
  }, [load])

  if (error) return <p className="error">{error}</p>
  if (!market) return <p className="muted">불러오는 중…</p>

  const isOpen = market.status === 'OPEN'

  return (
    <div>
      <div className="card">
        <div className="row">
          <h3 style={{ flex: 1 }}>{market.title}</h3>
          <span className="badge">{STATUS_LABEL[market.status]}</span>
        </div>
        <p className="muted">
          {market.ticker_name ?? market.ticker} · {market.ticker} · 집행금액{' '}
          {krw(market.notional_krw)}원
        </p>
        {market.description && <p>{market.description}</p>}

        <OddsBar consensus={market.consensus} />

        <p className="muted">
          {market.consensus.participant_count}명 참여 · 총{' '}
          {points(market.consensus.total_stake)}p
        </p>
        <p className="muted">
          베팅 마감 {datetime(market.closes_at)}
          {isOpen && ` (${timeLeft(market.closes_at)})`} · 판정 {datetime(market.resolve_at)}
        </p>
        <p className="muted">
          판정 기준: 기준가 대비 {market.buy_threshold_pct}% 이상이면 매수 정답,{' '}
          {market.sell_threshold_pct}% 이하면 매도 정답, 그 사이는 홀딩
          {market.reference_price && ` · 기준가 ${krw(market.reference_price)}원`}
          {market.resolution_price && ` → 판정가 ${krw(market.resolution_price)}원`}
        </p>
        {market.winning_outcome && (
          <p>
            정답:{' '}
            <span className={`badge ${market.winning_outcome}`}>
              {OUTCOME_LABEL[market.winning_outcome]}
            </span>
          </p>
        )}
      </div>

      {isOpen && <AllocationForm market={market} onDone={load} />}

      {decision && <DecisionCard decision={decision} />}

      {member?.role === 'admin' && (
        <AdminPanel market={market} decision={decision} onChange={load} />
      )}

      {!isOpen && market.bets.length > 0 && (
        <div className="card">
          <h3>스터디원 의견</h3>
          <table>
            <thead>
              <tr>
                <th>회원</th>
                <th>선택</th>
                <th className="num">스테이크</th>
                <th className="num">정산</th>
                <th>근거</th>
              </tr>
            </thead>
            <tbody>
              {market.bets.map((b) => (
                <tr key={b.id}>
                  <td>#{b.member_id}</td>
                  <td>
                    <span className={`badge ${b.outcome}`}>{OUTCOME_LABEL[b.outcome]}</span>
                  </td>
                  <td className="num">{points(b.stake)}p</td>
                  <td className="num">{b.payout ? `${points(b.payout)}p` : '-'}</td>
                  <td className="muted">{b.rationale ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
