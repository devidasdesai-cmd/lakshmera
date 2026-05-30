// Shared types and pure utilities — safe to import in both server and client components.

export interface Trade {
  id: number
  ticker: string
  side: string
  amount_usd: string | null
  contract_count: number | null
  price_paid: string | null
  our_probability: string
  market_probability: string
  result: string | null
  pnl: string | null
  created_at: string
  gfs_run: string | null
  strategy_version: string | null
}

export interface Signal {
  city: string
  ticker: string
  our_probability: string
  market_probability: string
  edge: string
  action: string
  created_at: string
}

export interface Health {
  last_signal_at: string | null
  signals_today: string
  runs_today: string
}

// Days between two YYYY-MM-DD date strings (b - a). NaN-safe.
export function daysBetween(a: string, b: string): number {
  const da = new Date(a + 'T00:00:00Z').getTime()
  const db = new Date(b + 'T00:00:00Z').getTime()
  if (isNaN(da) || isNaN(db)) return 0
  return Math.round((db - da) / 86400000)
}

// Today's date in UTC as YYYY-MM-DD.
export function todayUtc(): string {
  return new Date().toISOString().slice(0, 10)
}

// "5h 12m ago" / "2m ago" / "just now" / "3d ago"
export function timeAgo(isoTs: string | null): string {
  if (!isoTs) return 'never'
  const then = new Date(isoTs).getTime()
  const now = Date.now()
  let s = Math.max(0, Math.floor((now - then) / 1000))
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60); s -= m * 60
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  const remM = m - h * 60
  if (h < 24) return remM > 0 ? `${h}h ${remM}m ago` : `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

// SVG polyline `points` attribute for a sparkline. Values is array of numbers,
// width/height in svg coords. Auto-fits to min/max with 5% padding.
export function sparklinePoints(values: number[], width: number, height: number): string {
  if (values.length < 2) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const pad = height * 0.05
  return values.map((v, i) => {
    const x = (i / (values.length - 1)) * width
    const y = height - pad - ((v - min) / range) * (height - pad * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

export const SERIES_TO_CITY: Record<string, string> = {
  KXHIGHTDAL:  'Dallas',
  KXHIGHTHOU:  'Houston',
  KXHIGHNY:    'New York',
  KXHIGHNY0:   'New York',
  KXHIGHTBOS:  'Boston',
  KXHIGHTMIN:  'Minneapolis',
  KXHIGHLAX:   'Los Angeles',
  KXHIGHTPHX:  'Phoenix',
  KXHIGHTDC:   'DC',
  KXHIGHTLV:   'Las Vegas',
  KXHIGHTSEA:  'Seattle',
  KXHIGHTSATX: 'San Antonio',
  KXHIGHTSFO:  'San Francisco',
  KXHIGHTOKC:  'Oklahoma City',
  // Rain series
  KXRAINDALM:  'Dallas',
  KXRAINHOUM:  'Houston',
  KXRAINCHIM:  'Chicago',
  KXRAINSEAM:  'Seattle',
  KXRAINLAXM:  'Los Angeles',
  KXRAINSFOM:  'San Francisco',
  KXRAINMIAM:  'Miami',
  KXRAINNYCM:  'New York',
  KXRAINDENM:  'Denver',
  KXRAINAUSM:  'Austin',
  KXRAINNO:    'New Orleans',
}

const MONTHS: Record<string, number> = {
  JAN: 0, FEB: 1, MAR: 2, APR: 3, MAY: 4,  JUN: 5,
  JUL: 6, AUG: 7, SEP: 8, OCT: 9, NOV: 10, DEC: 11,
}

export interface ParsedTicker {
  city: string
  dateDisplay: string
  typeCode: string
  targetDate: Date | null
  targetDateStr: string  // YYYY-MM-DD for filter comparison
  isRain: boolean
}

const RAIN_SERIES = new Set(Object.keys(SERIES_TO_CITY).filter(k => k.startsWith('KXRAIN')))

function daysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate()
}

export function parseTicker(ticker: string): ParsedTicker {
  const parts   = ticker.split('-')
  const series  = parts[0] ?? ''
  const dateStr = parts[1] ?? ''
  const thirdPart = parts[2] ?? ''
  const city    = SERIES_TO_CITY[series] ?? series
  const isRain  = RAIN_SERIES.has(series)

  let dateDisplay   = dateStr
  let targetDate: Date | null = null
  let targetDateStr = ''
  let typeCode      = thirdPart

  if (isRain) {
    // Rain format: YYMON (e.g. 26MAY) — monthly contract
    const m = dateStr.match(/^(\d{2})([A-Z]{3})$/)
    if (m) {
      const year  = 2000 + parseInt(m[1])
      const month = MONTHS[m[2]] ?? 0
      const lastDay = daysInMonth(year, month)
      targetDate    = new Date(year, month, lastDay)
      dateDisplay   = targetDate.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
      const mo      = String(month + 1).padStart(2, '0')
      const dy      = String(lastDay).padStart(2, '0')
      targetDateStr = `${year}-${mo}-${dy}`
    }
    // Show threshold as >X" instead of bare number
    if (thirdPart) typeCode = `>${thirdPart}"`
  } else {
    // Temperature format: YYMONDD (e.g. 26MAY09)
    const m = dateStr.match(/^(\d{2})([A-Z]{3})(\d{2})$/)
    if (m) {
      targetDate    = new Date(2000 + parseInt(m[1]), MONTHS[m[2]] ?? 0, parseInt(m[3]))
      dateDisplay   = targetDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      const yr      = targetDate.getFullYear()
      const mo      = String(targetDate.getMonth() + 1).padStart(2, '0')
      const dy      = String(targetDate.getDate()).padStart(2, '0')
      targetDateStr = `${yr}-${mo}-${dy}`
    }
  }

  return { city, dateDisplay, typeCode, targetDate, targetDateStr, isRain }
}

export function pct(val: string | number | null): string {
  if (val === null || val === undefined) return '—'
  return `${(parseFloat(String(val)) * 100).toFixed(0)}%`
}

export function dollars(val: string | number | null): string {
  if (val === null || val === undefined) return '—'
  const n = parseFloat(String(val))
  const formatted = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return `${n >= 0 ? '+' : '-'}$${formatted}`
}

export function currency(val: string | number | null): string {
  if (val === null || val === undefined) return '—'
  const n = parseFloat(String(val))
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
