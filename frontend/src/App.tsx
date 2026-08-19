import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './lib/auth'
import { points } from './lib/format'
import { LeaderboardPage } from './pages/Leaderboard'
import { LoginPage } from './pages/Login'
import { MarketDetailPage } from './pages/MarketDetail'
import { MarketsPage } from './pages/Markets'
import { NewMarketPage } from './pages/NewMarket'
import { OrdersPage } from './pages/Orders'

/** 지금 실계좌로 나가는 상태인지 항상 눈에 보이게 한다. */
function ModeBanner() {
  const { status } = useAuth()
  if (!status) return null

  if (status.kill_switch) {
    return <div className="banner live">킬 스위치 ON — 모든 주문이 차단됩니다.</div>
  }
  if (status.live_trading_enabled) {
    return (
      <div className="banner live">
        실계좌 모드 — 승인한 주문은 실제 돈으로 체결됩니다. (1회 한도{' '}
        {points(status.max_order_amount_krw)}원)
      </div>
    )
  }
  return (
    <div className="banner paper">
      {status.broker_backend === 'mock' ? '모의 브로커' : '모의투자 계좌'} 모드 — 실제 주문은
      나가지 않습니다.
    </div>
  )
}

export function App() {
  const { member, loading, logout } = useAuth()

  if (loading) return <div className="app">불러오는 중…</div>
  if (!member) return <LoginPage />

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">스터디 펀드</span>
        <nav>
          <NavLink to="/" end>
            마켓
          </NavLink>
          <NavLink to="/leaderboard">순위</NavLink>
          <NavLink to="/orders">주문</NavLink>
          {member.role === 'admin' && <NavLink to="/admin/markets/new">마켓 개설</NavLink>}
        </nav>
        <span className="spacer" />
        <span className="muted">
          {member.name} · {points(member.balance)}p
        </span>
        <button className="secondary" onClick={logout}>
          로그아웃
        </button>
      </header>

      <ModeBanner />

      <Routes>
        <Route path="/" element={<MarketsPage />} />
        <Route path="/markets/:id" element={<MarketDetailPage />} />
        <Route path="/admin/markets/new" element={<NewMarketPage />} />
        <Route path="/leaderboard" element={<LeaderboardPage />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}
