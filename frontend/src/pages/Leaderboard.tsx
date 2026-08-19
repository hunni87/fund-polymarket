import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Score } from '../api/types'
import { points } from '../lib/format'

export function LeaderboardPage() {
  const [scores, setScores] = useState<Score[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .leaderboard()
      .then(setScores)
      .catch((e) => setError(e instanceof Error ? e.message : '불러오지 못했습니다.'))
  }, [])

  if (error) return <p className="error">{error}</p>

  return (
    <div className="card">
      <h3>스터디원 성적</h3>
      <p className="muted">
        Brier score는 확신 정도까지 반영한 정확도입니다. 낮을수록 좋습니다 — 몰빵해서 맞힌
        것과 신중하게 맞힌 것을 구분합니다.
      </p>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>이름</th>
            <th className="num">보유 포인트</th>
            <th className="num">순손익</th>
            <th className="num">적중</th>
            <th className="num">적중률</th>
            <th className="num">Brier</th>
          </tr>
        </thead>
        <tbody>
          {scores.map((s, i) => (
            <tr key={s.member_id}>
              <td>{i + 1}</td>
              <td>{s.name}</td>
              <td className="num">{points(s.balance)}p</td>
              <td className="num" style={{ color: Number(s.net_profit) >= 0 ? '#22c55e' : '#ef4444' }}>
                {Number(s.net_profit) >= 0 ? '+' : ''}
                {points(s.net_profit)}p
              </td>
              <td className="num">
                {s.hits}/{s.settled_markets}
              </td>
              <td className="num">{(Number(s.hit_rate) * 100).toFixed(0)}%</td>
              <td className="num">{s.brier ? Number(s.brier).toFixed(3) : '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
