import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Order } from '../api/types'
import { useAuth } from '../lib/auth'
import { datetime, krw } from '../lib/format'

const STATUS_LABEL: Record<string, string> = {
  PENDING: '준비',
  SUBMITTED: '접수 (체결 대기)',
  PARTIALLY_FILLED: '부분 체결',
  FILLED: '체결 완료',
  REJECTED: '거부',
  CANCELLED: '취소',
}

/** 아직 증권사에 물어볼 게 남은 주문. 이게 있어야 "동기화" 버튼이 의미가 있다. */
function isOpen(order: Order): boolean {
  return order.status === 'SUBMITTED' || order.status === 'PARTIALLY_FILLED'
}

function FillCell({ order }: { order: Order }) {
  if (order.status === 'REJECTED') return <span className="muted">-</span>
  return (
    <>
      <div>
        {order.filled_quantity} / {order.quantity}
      </div>
      {order.filled_avg_price && (
        <div className="muted">평균 {krw(order.filled_avg_price)}원</div>
      )}
    </>
  )
}

export function OrdersPage() {
  const { member } = useAuth()
  const [orders, setOrders] = useState<Order[]>([])
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncNote, setSyncNote] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .orders()
      .then(setOrders)
      .catch((e) => setError(e instanceof Error ? e.message : '불러오지 못했습니다.'))
  }, [])

  useEffect(load, [load])

  async function sync() {
    setSyncing(true)
    setSyncNote(null)
    try {
      const result = await api.syncOrders()
      setSyncNote(
        result.checked === 0
          ? '체결을 확인할 미체결 주문이 없습니다.'
          : `${result.checked}건 조회, ${result.updated.length}건 갱신` +
              (result.failed.length ? `, ${result.failed.length}건 조회 실패` : ''),
      )
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '동기화하지 못했습니다.')
    } finally {
      setSyncing(false)
    }
  }

  if (error) return <p className="error">{error}</p>
  if (orders.length === 0) return <p className="muted">아직 집행된 주문이 없습니다.</p>

  const openCount = orders.filter(isOpen).length

  return (
    <div className="card">
      <div className="row-between">
        <h3>주문 내역</h3>
        {member?.role === 'admin' && (
          <button disabled={syncing} onClick={sync}>
            {syncing ? '조회 중…' : '체결 동기화'}
          </button>
        )}
      </div>

      {openCount > 0 && (
        <p className="muted">
          체결 대기 중인 주문 {openCount}건. 스케줄러가 주기적으로 확인합니다.
        </p>
      )}
      {syncNote && <p className="muted">{syncNote}</p>}

      <table>
        <thead>
          <tr>
            <th>접수</th>
            <th>종목</th>
            <th>구분</th>
            <th className="num">체결/주문</th>
            <th className="num">주문가</th>
            <th>환경</th>
            <th>상태</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>{datetime(o.submitted_at ?? o.created_at)}</td>
              <td>{o.ticker}</td>
              <td>
                <span className={`badge ${o.side}`}>{o.side === 'BUY' ? '매수' : '매도'}</span>
              </td>
              <td className="num">
                <FillCell order={o} />
              </td>
              <td className="num">{krw(o.price)}</td>
              <td>
                <span className="badge">{o.broker_env}</span>
              </td>
              <td>
                {STATUS_LABEL[o.status] ?? o.status}
                {o.filled_at && <div className="muted">{datetime(o.filled_at)} 체결</div>}
                {o.error_message && <div className="error">{o.error_message}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
