import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { Fund, Quote } from '../api/types'
import { TickerPicker } from '../components/TickerPicker'
import { useAuth } from '../lib/auth'
import { krw } from '../lib/format'

/** datetime-local 입력은 로컬 시간 문자열을 쓴다. 서버는 UTC ISO를 받는다. */
function toIso(local: string): string {
  return new Date(local).toISOString()
}

function localInputValue(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function defaultTimes(): { closes: string; resolves: string } {
  const now = Date.now()
  return {
    closes: localInputValue(new Date(now + 24 * 3_600_000)),
    resolves: localInputValue(new Date(now + 6 * 24 * 3_600_000)),
  }
}

export function NewMarketPage() {
  const { member } = useAuth()
  const navigate = useNavigate()
  const times = useMemo(defaultTimes, [])

  const [funds, setFunds] = useState<Fund[]>([])
  const [fundId, setFundId] = useState<number | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [ticker, setTicker] = useState('')
  const [tickerName, setTickerName] = useState<string | undefined>()
  const [quote, setQuote] = useState<Quote | null>(null)
  const [closesAt, setClosesAt] = useState(times.closes)
  const [resolveAt, setResolveAt] = useState(times.resolves)
  const [notional, setNotional] = useState('500000')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .funds()
      .then((list) => {
        setFunds(list)
        if (list.length > 0) setFundId(list[0].id)
      })
      .catch((e) => setError(e instanceof Error ? e.message : '펀드를 불러오지 못했습니다.'))
  }, [])

  // 주문금액만 보고는 몇 주가 나갈지 감이 안 온다. 현재가를 알면 바로 보여줄 수 있다.
  const estimatedShares = useMemo(() => {
    const price = Number(quote?.price ?? 0)
    const amount = Number(notional)
    if (!price || !amount) return null
    return Math.floor(amount / price)
  }, [quote, notional])

  if (member?.role !== 'admin') {
    return <p className="error">운영자만 마켓을 개설할 수 있습니다.</p>
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    if (!fundId) return setError('펀드를 먼저 만들어야 합니다.')
    if (!ticker.trim()) return setError('종목을 입력하세요.')
    if (new Date(resolveAt) <= new Date(closesAt)) {
      return setError('판정 시각은 마감 시각 이후여야 합니다.')
    }

    setSaving(true)
    try {
      const market = await api.createMarket({
        fund_id: fundId,
        title: title.trim(),
        ticker: ticker.trim(),
        ticker_name: tickerName ?? null,
        description: description.trim() || null,
        closes_at: toIso(closesAt),
        resolve_at: toIso(resolveAt),
        notional_krw: notional,
      })
      navigate(`/markets/${market.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '마켓을 만들지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="card form" onSubmit={submit}>
      <h3>마켓 개설</h3>

      <label>
        <span>펀드</span>
        <select
          value={fundId ?? ''}
          onChange={(e) => setFundId(Number(e.target.value))}
          disabled={funds.length === 0}
        >
          {funds.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name} ({f.account_no})
            </option>
          ))}
        </select>
        {funds.length === 0 && <small className="error">펀드가 없습니다.</small>}
      </label>

      <label>
        <span>종목</span>
        <TickerPicker
          ticker={ticker}
          onChange={(t, name) => {
            setTicker(t)
            setTickerName(name)
          }}
          onQuote={setQuote}
        />
      </label>

      <label>
        <span>제목</span>
        <input
          value={title}
          required
          maxLength={200}
          placeholder={
            tickerName ? `${tickerName} — 이번 주 액션은?` : '삼성전자 — 이번 주 액션은?'
          }
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>

      <label>
        <span>설명 (선택)</span>
        <textarea
          value={description}
          rows={3}
          placeholder="판단에 참고할 배경을 적어두면 나중에 복기하기 좋습니다."
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>

      <div className="form-grid">
        <label>
          <span>베팅 마감</span>
          <input
            type="datetime-local"
            value={closesAt}
            required
            onChange={(e) => setClosesAt(e.target.value)}
          />
        </label>
        <label>
          <span>판정 시각</span>
          <input
            type="datetime-local"
            value={resolveAt}
            required
            onChange={(e) => setResolveAt(e.target.value)}
          />
        </label>
      </div>

      <label>
        <span>집행 금액 (원)</span>
        <input
          type="number"
          min={1}
          // step 을 만원 단위로 잡으면 브라우저가 min 기준 배수만 허용해서
          // 500,000 같은 평범한 값이 거부된다. 자릿수 제약을 두지 않는다.
          step="any"
          value={notional}
          required
          onChange={(e) => setNotional(e.target.value)}
        />
        <small className="muted">
          매수로 결정됐을 때 쓸 금액입니다.
          {estimatedShares !== null &&
            ` 현재가 ${krw(quote?.price)}원 기준 약 ${estimatedShares}주.`}
        </small>
      </label>

      {error && <p className="error">{error}</p>}

      <div className="row">
        <button type="submit" disabled={saving}>
          {saving ? '만드는 중…' : '마켓 열기'}
        </button>
        <button type="button" className="secondary" onClick={() => navigate('/')}>
          취소
        </button>
      </div>
    </form>
  )
}
