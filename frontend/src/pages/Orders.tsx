import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Order } from '../api/types'
import { datetime, krw } from '../lib/format'

export function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .orders()
      .then(setOrders)
      .catch((e) => setError(e instanceof Error ? e.message : '불러오지 못했습니다.'))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (orders.length === 0) return <p className="muted">아직 집행된 주문이 없습니다.</p>

  return (
    <div className="card">
      <h3>주문 내역</h3>
      <table>
        <thead>
          <tr>
            <th>시각</th>
            <th>종목</th>
            <th>구분</th>
            <th className="num">수량</th>
            <th className="num">가격</th>
            <th>환경</th>
            <th>상태</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>{datetime(o.created_at)}</td>
              <td>{o.ticker}</td>
              <td>
                <span className={`badge ${o.side}`}>{o.side === 'BUY' ? '매수' : '매도'}</span>
              </td>
              <td className="num">{o.quantity}</td>
              <td className="num">{krw(o.price)}</td>
              <td>
                <span className="badge">{o.broker_env}</span>
              </td>
              <td>
                {o.status}
                {o.error_message && <div className="error">{o.error_message}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
