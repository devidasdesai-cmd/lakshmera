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
