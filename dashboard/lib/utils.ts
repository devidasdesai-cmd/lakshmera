// Shared types and pure utilities — safe to import in both server and client components.

export interface Trade {
  id: number
  ticker: string
  side: string
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
}

export function parseTicker(ticker: string): ParsedTicker {
  const [series = '', dateStr = '', typeCode = ''] = ticker.split('-')
  const city = SERIES_TO_CITY[series] ?? series

  let dateDisplay = dateStr
  let targetDate: Date | null = null
  let targetDateStr = ''

  const m = dateStr.match(/^(\d{2})([A-Z]{3})(\d{2})$/)
  if (m) {
    targetDate    = new Date(2000 + parseInt(m[1]), MONTHS[m[2]] ?? 0, parseInt(m[3]))
    dateDisplay   = targetDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    const yr      = targetDate.getFullYear()
    const mo      = String(targetDate.getMonth() + 1).padStart(2, '0')
    const dy      = String(targetDate.getDate()).padStart(2, '0')
    targetDateStr = `${yr}-${mo}-${dy}`
  }

  return { city, dateDisplay, typeCode, targetDate, targetDateStr }
}

export function pct(val: string | number | null): string {
  if (val === null || val === undefined) return '—'
  return `${(parseFloat(String(val)) * 100).toFixed(0)}%`
}

export function dollars(val: string | number | null): string {
  if (val === null || val === undefined) return '—'
  const n = parseFloat(String(val))
  return `${n >= 0 ? '+' : ''}$${Math.abs(n).toFixed(2)}`
}
