import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { STATUS_LABEL, type Market } from '../api/types'
import { OddsBar } from '../components/OddsBar'
import { datetime, krw, timeLeft } from '../lib/format'

/** 목록에서도 확률을 보여주려면 마켓별 합의를 따로 받아야 한다. */
function MarketCard({ market }: { market: Market }) {
  const [consensus, setConsensus] = useState<Awaited<
    ReturnType<typeof api.market>
  >['consensus'] | null>(null)

  useEffect(() => {
    api
      .market(market.id)
      .then((d) => setConsensus(d.consensus))
      .catch(() => setConsensus(null))
  }, [market.id])

  return (
    <Link to={`/markets/${market.id}`}>
      <div className="card">
        <div className="row">
          <h3 style={{ flex: 1 }}>{market.title}</h3>
          <span className="badge">{STATUS_LABEL[market.status]}</span>
        </div>
        <p className="muted">
          {market.ticker_name ?? market.ticker} · {market.ticker} · 집행금액{' '}
          {krw(market.notional_krw)}원
        </p>

        {consensus && <OddsBar consensus={consensus} />}

        <p className="muted">
          {market.status === 'OPEN'
            ? `베팅 마감 ${timeLeft(market.closes_at)} (${datetime(market.closes_at)})`
            : `판정 ${datetime(market.resolve_at)}`}
          {consensus ? ` · ${consensus.participant_count}명 참여` : ''}
          {market.winning_outcome ? ` · 정답 ${market.winning_outcome}` : ''}
        </p>
      </div>
    </Link>
  )
}

export function MarketsPage() {
  const [markets, setMarkets] = useState<Market[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .markets()
      .then(setMarkets)
      .catch((e) => setError(e instanceof Error ? e.message : '불러오지 못했습니다.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="muted">불러오는 중…</p>
  if (error) return <p className="error">{error}</p>
  if (markets.length === 0) {
    return <p className="muted">아직 열린 마켓이 없습니다. 운영자가 주제를 만들면 여기에 나타납니다.</p>
  }

  return (
    <div>
      {markets.map((m) => (
        <MarketCard key={m.id} market={m} />
      ))}
    </div>
  )
}
