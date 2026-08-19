import { useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import type { Quote, Symbol } from '../api/types'
import { krw } from '../lib/format'

interface Props {
  ticker: string
  onChange: (ticker: string, name?: string) => void
  onQuote: (quote: Quote | null) => void
}

/**
 * 종목 입력. 이름으로 찾고, 고른 뒤에는 증권사에 실제로 물어본다.
 *
 * 로컬 마스터 검색과 증권사 조회를 나눈 이유: 마스터는 낡을 수 있고 증권사가 진실이다.
 * 마스터가 비어 있어도 티커만 알면 조회로 진행할 수 있어야 한다.
 */
export function TickerPicker({ ticker, onChange, onQuote }: Props) {
  const [query, setQuery] = useState(ticker)
  const [matches, setMatches] = useState<Symbol[]>([])
  const [quote, setQuote] = useState<Quote | null>(null)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)

  useEffect(() => {
    const q = query.trim()
    if (q.length < 1) {
      setMatches([])
      return
    }
    // 타이핑마다 때리지 않는다.
    const timer = setTimeout(() => {
      const seq = ++latest.current
      api
        .searchSymbols(q)
        .then((found) => {
          // 늦게 도착한 옛 응답이 최신 결과를 덮어쓰지 않게 한다.
          if (seq === latest.current) setMatches(found)
        })
        .catch(() => setMatches([]))
    }, 200)
    return () => clearTimeout(timer)
  }, [query])

  // 고른 종목을 확인한 뒤에는 후보 목록을 감춘다. 별도 open 플래그를 두면
  // 비동기 검색 결과가 늦게 도착할 때 상태가 어긋난다 — 확인 여부에서 직접 끌어낸다.
  const confirmed = quote !== null && quote.ticker === query.trim()

  function pick(symbol: Symbol) {
    setQuery(symbol.ticker)
    onChange(symbol.ticker, symbol.name)
    void check(symbol.ticker)
  }

  async function check(target: string) {
    const code = target.trim()
    if (!code) return
    setChecking(true)
    setError(null)
    try {
      const result = await api.quoteSymbol(code)
      setQuote(result)
      onQuote(result)
      onChange(code, result.name ?? undefined)
    } catch (e) {
      setQuote(null)
      onQuote(null)
      setError(e instanceof Error ? e.message : '종목을 확인하지 못했습니다.')
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="ticker-picker">
      <div className="row">
        <input
          value={query}
          placeholder="종목명 또는 티커 (예: 삼성전자, 005930)"
          onChange={(e) => {
            setQuery(e.target.value)
            setQuote(null)
            onQuote(null)
            onChange(e.target.value.trim())
          }}
        />
        <button
          type="button"
          className="secondary"
          disabled={checking || !query.trim()}
          onClick={() => check(query)}
        >
          {checking ? '조회 중…' : '시세 확인'}
        </button>
      </div>

      {!confirmed && matches.length > 0 && (
        <ul className="suggestions">
          {matches.map((s) => (
            <li key={s.ticker}>
              <button type="button" className="secondary" onClick={() => pick(s)}>
                <strong>{s.name}</strong> <span className="muted">{s.ticker}</span>
                {s.market && <span className="badge">{s.market}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      {quote && (
        <p className="success">
          {quote.name ?? quote.ticker} · 현재가 {krw(quote.price)}원
        </p>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}
