export function krw(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '-'
  return n.toLocaleString('ko-KR', { maximumFractionDigits: 0 })
}

export function points(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '-'
  return n.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
}

export function pct(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '-'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '-'
  return `${(n * 100).toFixed(0)}%`
}

export function datetime(iso: string | null | undefined): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function timeLeft(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now()
  if (ms <= 0) return '마감'
  const hours = Math.floor(ms / 3_600_000)
  if (hours >= 24) return `${Math.floor(hours / 24)}일 남음`
  if (hours >= 1) return `${hours}시간 남음`
  return `${Math.max(1, Math.floor(ms / 60_000))}분 남음`
}
