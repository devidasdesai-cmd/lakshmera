'use client'

import { useState, useMemo, useEffect } from 'react'
import { createPortal } from 'react-dom'
import Link from 'next/link'
import { Trade, Signal, Health, parseTicker, pct, dollars, currency, SERIES_TO_CITY, todayUtc, daysBetween, timeAgo, sparklinePoints } from '../../lib/utils'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Props {
  settled: Trade[]
  active:  Trade[]
  signals: Signal[]
  health:  Health
}

// --- Rolling-window aggregator: sums P&L for trades within last `days` of `today` ---
function rollingPnlByDay(trades: { pnl: string | null; targetDateStr: string }[], days: number, today: string): number[] {
  const out: number[] = new Array(days).fill(0)
  for (const t of trades) {
    if (!t.targetDateStr) continue
    const offset = daysBetween(t.targetDateStr, today)
    if (offset >= 0 && offset < days) {
      out[days - 1 - offset] += parseFloat(t.pnl ?? '0')
    }
  }
  // Cumulative for sparkline
  let acc = 0
  return out.map(v => (acc += v))
}

// --- Cron schedule (mirrors dashboard/vercel.json + .github/workflows/bot.yml) ---
const CRON_SCHEDULE_UTC = [
  { hour: 11, minute: 16, source: 'GitHub' },
  { hour: 16, minute: 37, source: 'Vercel' },
  { hour: 23, minute: 37, source: 'Vercel' },
]

function nextCronAt(now: Date): { iso: string; label: string } {
  const nowMs = now.getTime()
  let bestMs = Infinity
  let bestLabel = ''
  for (let dayOffset = 0; dayOffset <= 1; dayOffset++) {
    for (const c of CRON_SCHEDULE_UTC) {
      const t = new Date(Date.UTC(
        now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + dayOffset,
        c.hour, c.minute, 0
      ))
      const ms = t.getTime()
      if (ms > nowMs && ms < bestMs) {
        bestMs = ms
        bestLabel = `${String(c.hour).padStart(2, '0')}:${String(c.minute).padStart(2, '0')} UTC`
      }
    }
  }
  if (!isFinite(bestMs)) return { iso: '', label: '' }
  const mins = Math.floor((bestMs - nowMs) / 60000)
  const h = Math.floor(mins / 60)
  const m = mins - h * 60
  const inLabel = h > 0 ? `${h}h ${m}m` : `${m}m`
  return { iso: new Date(bestMs).toISOString(), label: `${bestLabel} (in ${inLabel})` }
}

type SortDir   = 'asc' | 'desc'
type SortState = { col: string; dir: SortDir }

interface EnrichedTrade extends Trade {
  city:          string
  dateDisplay:   string
  typeCode:      string
  targetDateStr: string
  isRain:        boolean
  edge:          number | null  // post-fee edge on the side bet at trade time
  threshold:     number | null
  bucketLow:     number | null
  bucketHigh:    number | null
  rangeDisplay:  string
}

// Kalshi fee is 7% on net profit of a winning contract.
const KALSHI_FEE_RATE = 0.07

function computeTradeEdge(t: Trade): number | null {
  const op = parseFloat(t.our_probability)
  const mp = parseFloat(t.market_probability)
  if (isNaN(op) || isNaN(mp)) return null
  if (t.side === 'yes') {
    // YES paid at price mp; fee = rate * (1 - mp)
    return op - mp - KALSHI_FEE_RATE * (1 - mp)
  }
  // NO paid at price (1 - mp); fee = rate * mp
  return (1 - op) - (1 - mp) - KALSHI_FEE_RATE * mp
}

interface EnrichedSignal extends Signal {
  dateDisplay:   string
  typeCode:      string
  targetDateStr: string
  isRain:        boolean
}

// ─── Enrichment ──────────────────────────────────────────────────────────────

function enrichTrade(t: Trade): EnrichedTrade {
  const p = parseTicker(t.ticker)
  return { ...t, city: p.city, dateDisplay: p.dateDisplay, typeCode: p.typeCode,
           targetDateStr: p.targetDateStr, isRain: p.isRain,
           threshold: p.threshold, bucketLow: p.bucketLow, bucketHigh: p.bucketHigh,
           rangeDisplay: p.rangeDisplay,
           edge: computeTradeEdge(t) }
}

function enrichSignal(s: Signal): EnrichedSignal {
  const { dateDisplay, typeCode, targetDateStr, isRain } = parseTicker(s.ticker)
  return { ...s, dateDisplay, typeCode, targetDateStr, isRain }
}

// ─── Sorting ─────────────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function sortValue(row: any, col: string): string | number {
  const v = row[col]
  if (v === null || v === undefined) return ''
  const n = parseFloat(String(v))
  return isNaN(n) ? String(v).toLowerCase() : n
}

function applySort<T>(rows: T[], { col, dir }: SortState): T[] {
  return [...rows].sort((a, b) => {
    const av = sortValue(a, col)
    const bv = sortValue(b, col)
    if (av === '' && bv !== '') return 1
    if (bv === '' && av !== '') return -1
    if (av < bv) return dir === 'asc' ? -1 : 1
    if (av > bv) return dir === 'asc' ?  1 : -1
    return 0
  })
}

function toggleSort(current: SortState, col: string): SortState {
  if (current.col === col) return { col, dir: current.dir === 'asc' ? 'desc' : 'asc' }
  return { col, dir: 'asc' }
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ColHeader({ label, tip, sortKey, sort, onSort }: {
  label:   string
  tip:     string
  sortKey: string
  sort:    SortState
  onSort:  (k: string) => void
}) {
  const [tipPos, setTipPos] = useState<{ x: number; y: number } | null>(null)
  const active = sort.col === sortKey

  return (
    <th className="px-4 py-2 text-left">
      <button
        onClick={() => onSort(sortKey)}
        onMouseEnter={e => {
          const r = e.currentTarget.getBoundingClientRect()
          setTipPos({ x: r.left, y: r.bottom + 6 })
        }}
        onMouseLeave={() => setTipPos(null)}
        className="inline-flex items-center gap-1 cursor-pointer"
      >
        <span className={`text-xs font-medium uppercase tracking-wider
          border-b border-dashed transition-colors
          ${active
            ? 'text-gray-800 dark:text-gray-200 border-gray-500 dark:border-gray-400'
            : 'text-gray-500 dark:text-gray-500 border-gray-300 dark:border-gray-700 hover:text-gray-700 dark:hover:text-gray-300'
          }`}>
          {label}
        </span>
        <span className="text-xs text-gray-400 dark:text-gray-600">
          {active ? (sort.dir === 'asc' ? '↑' : '↓') : '↕'}
        </span>
      </button>

      {tipPos && createPortal(
        <div
          className="fixed z-50 w-56 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-2.5
            text-xs text-gray-700 dark:text-gray-300 shadow-xl pointer-events-none leading-relaxed"
          style={{ left: tipPos.x, top: tipPos.y }}
        >
          {tip}
        </div>,
        document.body
      )}
    </th>
  )
}

function Section({ title, shown, total, children, className = 'border border-gray-200 dark:border-gray-800' }: {
  title:     string
  shown:     number
  total:     number
  children:  React.ReactNode
  className?: string
}) {
  return (
    <div className={`rounded-lg overflow-hidden ${className}`}>
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800">
        <h2 className="text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">{title}</h2>
        <span className="text-xs text-gray-400 dark:text-gray-600">
          {shown < total ? `${shown} of ${total}` : `${total} rows`}
        </span>
      </div>
      {children}
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-10 text-center text-sm text-gray-400 dark:text-gray-600">{children}</div>
}

function HeroCard({ label, value, subtitle, tone, spark, progress }: {
  label: string
  value: string
  subtitle: string
  tone: 'positive' | 'negative' | 'neutral'
  spark?: number[]
  progress?: number   // 0..1, only rendered when present
}) {
  const valueColor =
    tone === 'positive' ? 'text-emerald-600 dark:text-emerald-400'
    : tone === 'negative' ? 'text-red-600 dark:text-red-400'
    : 'text-gray-900 dark:text-white'
  const sparkStroke =
    tone === 'positive' ? 'stroke-emerald-500'
    : tone === 'negative' ? 'stroke-red-500'
    : 'stroke-sky-500'
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4 relative overflow-hidden">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold tabular-nums mt-1 ${valueColor}`}>{value}</p>
      <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">{subtitle}</p>
      {spark && spark.length >= 2 && (
        <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="absolute bottom-1 right-1 w-20 h-6 opacity-50 pointer-events-none">
          <polyline
            fill="none"
            strokeWidth="1.5"
            className={sparkStroke}
            points={sparklinePoints(spark, 100, 24)}
          />
        </svg>
      )}
      {progress !== undefined && (
        <div className="mt-2 h-1 bg-gray-100 dark:bg-gray-800 rounded overflow-hidden">
          <div
            className={`h-full rounded ${tone === 'negative' ? 'bg-red-400 dark:bg-red-500' : 'bg-emerald-500 dark:bg-emerald-400'}`}
            style={{ width: `${Math.max(0, Math.min(100, progress * 100))}%` }}
          />
        </div>
      )}
    </div>
  )
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export default function Dashboard({ settled, active, signals, health }: Props) {

  // Theme
  const [isDark, setIsDark] = useState(true)

  useEffect(() => {
    const stored = localStorage.getItem('theme')
    const dark = stored !== 'light'
    setIsDark(dark)
    document.documentElement.classList.toggle('dark', dark)
  }, [])

  function toggleTheme() {
    const newDark = !isDark
    setIsDark(newDark)
    document.documentElement.classList.toggle('dark', newDark)
    localStorage.setItem('theme', newDark ? 'dark' : 'light')
  }

  // Filter state
  const [fromDate, setFromDate] = useState('')
  const [toDate,   setToDate]   = useState('')
  const [city,     setCity]     = useState('')

  // Sort state (independent per table)
  const [settledSort, setSettledSort] = useState<SortState>({ col: 'targetDateStr', dir: 'desc' })
  const [activeSort,  setActiveSort]  = useState<SortState>({ col: 'targetDateStr', dir: 'asc'  })
  const [signalSort,  setSignalSort]  = useState<SortState>({ col: 'targetDateStr', dir: 'desc' })
  const [signalMode,  setSignalMode]  = useState<'actionable' | 'all'>('actionable')

  // Enrich once
  const enrichedSettled = useMemo(() => settled.map(enrichTrade),  [settled])
  const enrichedActive  = useMemo(() => active.map(enrichTrade),   [active])
  const enrichedSignals = useMemo(() => signals.map(enrichSignal), [signals])

  // City list for dropdown
  const cities = useMemo(() => {
    const s = new Set<string>()
    enrichedSettled.forEach(r => s.add(r.city))
    enrichedActive.forEach(r  => s.add(r.city))
    enrichedSignals.forEach(r => s.add(r.city))
    return Array.from(s).sort()
  }, [enrichedSettled, enrichedActive, enrichedSignals])

  // Apply filters
  function applyFilters<T extends { targetDateStr: string; city: string }>(rows: T[]): T[] {
    return rows.filter(r => {
      if (fromDate && r.targetDateStr && r.targetDateStr < fromDate) return false
      if (toDate   && r.targetDateStr && r.targetDateStr > toDate)   return false
      if (city     && r.city !== city)                               return false
      return true
    })
  }

  const filteredSettled = useMemo(() => applyFilters(enrichedSettled), [enrichedSettled, fromDate, toDate, city])
  const filteredActive  = useMemo(() => applyFilters(enrichedActive),  [enrichedActive,  fromDate, toDate, city])
  // Signals get an extra "actionable" filter: actionable = anything except the
  // boring NO_BET/edge_too_low case. Default 'actionable' to keep the log
  // scannable; toggle 'all' to see every market evaluation including the
  // ~90% of NO_BETs that are just "no edge here, moving on."
  const filteredSignalsBeforeMode = useMemo(() => applyFilters(enrichedSignals), [enrichedSignals, fromDate, toDate, city])
  const filteredSignals = useMemo(() => {
    if (signalMode === 'all') return filteredSignalsBeforeMode
    return filteredSignalsBeforeMode.filter(s =>
      s.action !== 'NO_BET' || (s.reason !== null && s.reason !== 'edge_too_low')
    )
  }, [filteredSignalsBeforeMode, signalMode])

  const sortedSettled = useMemo(() => applySort(filteredSettled, settledSort), [filteredSettled, settledSort])
  const sortedActive  = useMemo(() => applySort(filteredActive,  activeSort),  [filteredActive,  activeSort])
  const sortedSignals = useMemo(() => applySort(filteredSignals, signalSort),  [filteredSignals, signalSort])

  // Capital flow (unfiltered — full picture of bot's capital usage)
  const settledWonStakes  = enrichedSettled.filter(t => parseFloat(t.pnl ?? '0') > 0)
                              .reduce((s, t) => s + parseFloat(t.amount_usd ?? '0'), 0)
  const settledWonProfit  = enrichedSettled.filter(t => parseFloat(t.pnl ?? '0') > 0)
                              .reduce((s, t) => s + parseFloat(t.pnl ?? '0'), 0)
  const settledLostAmount = enrichedSettled.filter(t => parseFloat(t.pnl ?? '0') <= 0)
                              .reduce((s, t) => s + Math.abs(parseFloat(t.pnl ?? '0')), 0)
  const recycledFromWins  = settledWonStakes + settledWonProfit
  const settledDeployed   = enrichedSettled.reduce((s, t) => s + parseFloat(t.amount_usd ?? '0'), 0)
  const openDeployed      = enrichedActive.reduce((s, t)  => s + parseFloat(t.amount_usd ?? '0'), 0)
  const grossDeployed     = settledDeployed + openDeployed
  const netFromCapital    = grossDeployed - recycledFromWins

  // Filtered stats
  const filteredPnl      = filteredSettled.reduce((s, t) => s + parseFloat(t.pnl ?? '0'), 0)
  const filteredWins     = filteredSettled.filter(t => parseFloat(t.pnl ?? '0') > 0).length
  const filteredLosses   = filteredSettled.filter(t => parseFloat(t.pnl ?? '0') <= 0).length
  const filteredWinRate  = filteredSettled.length > 0
    ? `${(filteredWins / filteredSettled.length * 100).toFixed(1)}%`
    : '—'
  const filteredCapital  = filteredSettled.reduce((s, t) => s + parseFloat(t.amount_usd ?? '0'), 0)
  const filteredReturn   = filteredCapital > 0 ? (filteredPnl / filteredCapital) * 100 : null

  const filtersActive = !!(fromDate || toDate || city)

  // ── Rolling-window metrics (today / 7d / 30d) — for the hero row ──
  const today = todayUtc()
  // Hero P&L cards reflect daily *temperature* activity. Rain is monthly and
  // gets its own dedicated tile below — mixing the two distorts daily reads
  // because rain dumps a chunk on the last day of each month.
  const enrichedSettledTemp = enrichedSettled.filter(t => !t.isRain)

  // "Last 24h P&L" — settlements for yesterday's target date (today's contracts
  // settle tonight at each city's local midnight, so "today's settlements"
  // would be empty until late evening). Yesterday is what just resolved.
  const yesterday = (() => {
    const d = new Date()
    d.setUTCDate(d.getUTCDate() - 1)
    return d.toISOString().slice(0, 10)
  })()
  const recentPnl   = enrichedSettledTemp
    .filter(t => t.targetDateStr === yesterday)
    .reduce((s, t) => s + parseFloat(t.pnl ?? '0'), 0)
  const recentCount = enrichedSettledTemp.filter(t => t.targetDateStr === yesterday).length
  const recentWins  = enrichedSettledTemp.filter(t => t.targetDateStr === yesterday && parseFloat(t.pnl ?? '0') > 0).length
  const series14 = rollingPnlByDay(enrichedSettledTemp, 14, today)
  const series30 = rollingPnlByDay(enrichedSettledTemp, 30, today)

  // Rain · last month aggregate — find the most recent month that has any
  // settled rain trades, and aggregate. Rain contracts have targetDateStr =
  // last day of the month, so grouping by YYYY-MM gives us monthly buckets.
  const rainSettled = enrichedSettled.filter(t => t.isRain)
  const rainByMonth = new Map<string, typeof enrichedSettled>()
  for (const t of rainSettled) {
    const monthKey = t.targetDateStr.slice(0, 7)
    if (!monthKey) continue
    if (!rainByMonth.has(monthKey)) rainByMonth.set(monthKey, [])
    rainByMonth.get(monthKey)!.push(t)
  }
  const latestRainMonth = Array.from(rainByMonth.keys()).sort().pop() ?? null
  const latestRainTrades = latestRainMonth ? rainByMonth.get(latestRainMonth)! : []
  const rainPnl   = latestRainTrades.reduce((s, t) => s + parseFloat(t.pnl ?? '0'), 0)
  const rainCount = latestRainTrades.length
  const rainWins  = latestRainTrades.filter(t => parseFloat(t.pnl ?? '0') > 0).length
  const rainMonthLabel = latestRainMonth
    ? new Date(latestRainMonth + '-15T00:00:00Z').toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
    : null
  const last7Pnl  = series14[13] - (series14[6] ?? 0)
  const last30Pnl = series30[29]
  const TARGET_MONTHLY = 2000

  // ── V1 vs V2 attribution ──
  const v1Settled = enrichedSettled.filter(t => (t.strategy_version ?? 'v1') === 'v1')
  const v2Settled = enrichedSettled.filter(t => t.strategy_version === 'v2')
  function strategyStats(arr: typeof enrichedSettled) {
    const n = arr.length
    const wins = arr.filter(t => parseFloat(t.pnl ?? '0') > 0).length
    const pnl  = arr.reduce((s, t) => s + parseFloat(t.pnl ?? '0'), 0)
    return { n, wins, pnl, wr: n ? wins / n * 100 : 0, avg: n ? pnl / n : 0 }
  }
  const v1Stat = strategyStats(v1Settled)
  const v2Stat = strategyStats(v2Settled)
  const v2Ready = v2Stat.n >= 50   // threshold from May 30 ship memo
  const v2Better = v2Ready && (v2Stat.pnl > v1Stat.pnl) && (v2Stat.wr >= v1Stat.wr - 5)

  // ── Bot health ──
  const now = new Date()
  const lastSignalAgoMs = health.last_signal_at
    ? now.getTime() - new Date(health.last_signal_at).getTime()
    : Infinity
  const lastSignalHours = lastSignalAgoMs / 3600000
  const healthStatus: 'ok' | 'warn' | 'critical' =
    lastSignalHours <= 8 ? 'ok' : lastSignalHours <= 24 ? 'warn' : 'critical'
  const next = nextCronAt(now)
  const runsToday = parseInt(health.runs_today, 10) || 0
  const signalsToday = parseInt(health.signals_today, 10) || 0

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-gray-900 dark:text-white">LAKSHMERA</h1>
          <p className="text-sm text-gray-500 mt-0.5">Weather Prediction Market Bot</p>
        </div>
        <div className="flex items-center gap-3 mt-1">
          <Link
            href="/analytics"
            className="text-sm font-medium text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
          >
            Analytics →
          </Link>
          <button
            onClick={toggleTheme}
            aria-label="Toggle light/dark mode"
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 transition-colors"
          >
            {isDark ? (
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="5"/>
                <line x1="12" y1="1" x2="12" y2="3"/>
                <line x1="12" y1="21" x2="12" y2="23"/>
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
                <line x1="1" y1="12" x2="3" y2="12"/>
                <line x1="21" y1="12" x2="23" y2="12"/>
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
              </svg>
            )}
          </button>
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
            PAPER TRADING
          </span>
        </div>
      </div>

      {/* Bot health strip */}
      <div className={`rounded-lg px-4 py-2.5 text-xs flex flex-wrap items-center gap-x-5 gap-y-1 ${
        healthStatus === 'ok'
          ? 'bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800'
          : healthStatus === 'warn'
          ? 'bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800'
          : 'bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800'
      }`}>
        <span className="flex items-center gap-1.5">
          <span className={`inline-block w-2 h-2 rounded-full ${
            healthStatus === 'ok' ? 'bg-emerald-500' : healthStatus === 'warn' ? 'bg-amber-500' : 'bg-red-500'
          }`}></span>
          <span className="font-semibold uppercase tracking-wider">
            {healthStatus === 'ok' ? 'Bot healthy' : healthStatus === 'warn' ? 'Bot lagging' : 'Bot stalled'}
          </span>
        </span>
        <span className="text-gray-600 dark:text-gray-300">
          Last signal: <span className="font-mono">{timeAgo(health.last_signal_at)}</span>
        </span>
        <span className="text-gray-600 dark:text-gray-300">
          Next cron: <span className="font-mono">{next.label || '—'}</span>
        </span>
        <span className="text-gray-600 dark:text-gray-300">
          Today: <span className="font-mono">{runsToday}</span> run{runsToday === 1 ? '' : 's'},{' '}
          <span className="font-mono">{signalsToday}</span> signals
        </span>
      </div>

      {/* Hero metrics: temp-only 24h/7d/30d, rain monthly, open risk. Temperature
          cards exclude rain because rain settles monthly in one chunk and would
          distort the daily reading; rain gets a dedicated tile. */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <HeroCard
          label="Last 24h P&L"
          value={dollars(recentPnl)}
          subtitle={recentCount > 0 ? `${recentWins}W · ${recentCount - recentWins}L · settled ${yesterday.slice(5)}` : 'no temp settlements yet'}
          tone={recentPnl >= 0 ? 'positive' : 'negative'}
          spark={series14}
        />
        <HeroCard
          label="7-day P&L"
          value={dollars(last7Pnl)}
          subtitle="rolling week (temp)"
          tone={last7Pnl >= 0 ? 'positive' : 'negative'}
          spark={series14}
        />
        <HeroCard
          label="30-day P&L"
          value={dollars(last30Pnl)}
          subtitle={`${Math.round(Math.max(0, last30Pnl) / TARGET_MONTHLY * 100)}% of $${TARGET_MONTHLY.toLocaleString()} target`}
          tone={last30Pnl >= 0 ? 'positive' : 'negative'}
          spark={series30}
          progress={Math.max(0, Math.min(1, last30Pnl / TARGET_MONTHLY))}
        />
        <HeroCard
          label={rainMonthLabel ? `Rain · ${rainMonthLabel}` : 'Rain · no data'}
          value={rainCount > 0 ? dollars(rainPnl) : '—'}
          subtitle={rainCount > 0 ? `${rainWins}W · ${rainCount - rainWins}L · monthly` : 'no settled rain bets yet'}
          tone={rainCount === 0 ? 'neutral' : rainPnl >= 0 ? 'positive' : 'negative'}
        />
        <HeroCard
          label="Capital at risk now"
          value={currency(openDeployed)}
          subtitle={`${enrichedActive.length} open position${enrichedActive.length === 1 ? '' : 's'}`}
          tone="neutral"
        />
      </div>

      {/* V1 vs V2 attribution */}
      <div>
        <p className="text-xs text-gray-400 dark:text-gray-600 uppercase tracking-wider mb-2 px-0.5">
          Strategy attribution {v2Ready ? `· V2 ready (${v2Stat.n} settled)` : `· V2 still collecting (${v2Stat.n} / 50 settled)`}
        </p>
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-950 text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                <th className="px-4 py-2 text-left font-medium"></th>
                <th className="px-4 py-2 text-right font-medium">Settled</th>
                <th className="px-4 py-2 text-right font-medium">Wins</th>
                <th className="px-4 py-2 text-right font-medium">Win rate</th>
                <th className="px-4 py-2 text-right font-medium">Total P&L</th>
                <th className="px-4 py-2 text-right font-medium">Avg / trade</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
              {[
                { label: 'V1 (legacy: ensemble fraction + α=0.5)', stat: v1Stat, isWinner: v2Ready && !v2Better },
                { label: 'V2 (live since May 30: distribution-fit, σ=1.5°F)', stat: v2Stat, isWinner: v2Ready && v2Better },
              ].map(row => (
                <tr key={row.label} className={row.isWinner ? 'bg-emerald-50/50 dark:bg-emerald-950/20' : ''}>
                  <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 flex items-center gap-2">
                    <span className={`text-xs font-medium px-1.5 py-0.5 rounded border ${
                      row.label.startsWith('V1')
                        ? 'bg-gray-50 dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700'
                        : 'bg-violet-50 dark:bg-violet-950 text-violet-600 dark:text-violet-400 border-violet-200 dark:border-violet-800'
                    }`}>
                      {row.label.startsWith('V1') ? 'v1' : 'v2'}
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-500">{row.label.split(': ')[1]?.replace(')', '') ?? ''}</span>
                    {row.isWinner && (
                      <span className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 ml-1">▲ leading</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums font-mono text-xs text-gray-700 dark:text-gray-300">{row.stat.n}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums font-mono text-xs text-gray-700 dark:text-gray-300">{row.stat.wins}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums font-mono text-xs text-gray-700 dark:text-gray-300">{row.stat.n ? `${row.stat.wr.toFixed(1)}%` : '—'}</td>
                  <td className={`px-4 py-2.5 text-right tabular-nums font-medium ${row.stat.pnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                    {row.stat.n ? dollars(row.stat.pnl) : '—'}
                  </td>
                  <td className={`px-4 py-2.5 text-right tabular-nums font-mono text-xs ${row.stat.avg >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                    {row.stat.n ? `${row.stat.avg >= 0 ? '+' : ''}$${row.stat.avg.toFixed(2)}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!v2Ready && (
          <p className="text-xs text-gray-400 dark:text-gray-600 mt-1.5 px-0.5">
            Wait for V2 to reach 50 settled trades before reading attribution as decisive.
          </p>
        )}
      </div>

      {/* Capital flow — always unfiltered */}
      <div>
        <p className="text-xs text-gray-400 dark:text-gray-600 uppercase tracking-wider mb-2 px-0.5">Capital flow · all-time</p>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Gross Deployed</p>
            <p className="text-2xl font-bold tabular-nums mt-1 text-gray-900 dark:text-white">{currency(grossDeployed)}</p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">total dollars bet, all time</p>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Stakes Returned</p>
            <p className="text-2xl font-bold tabular-nums mt-1 text-emerald-600 dark:text-emerald-400">{currency(settledWonStakes)}</p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">original bet amounts won back</p>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Profit Earned</p>
            <p className="text-2xl font-bold tabular-nums mt-1 text-emerald-600 dark:text-emerald-400">{currency(settledWonProfit)}</p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">gains on top of returned stakes</p>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Net Losses</p>
            <p className="text-2xl font-bold tabular-nums mt-1 text-red-600 dark:text-red-400">{currency(settledLostAmount)}</p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">total lost on settled bets</p>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Net from Capital</p>
            <p className="text-2xl font-bold tabular-nums mt-1 text-gray-900 dark:text-white">{currency(netFromCapital)}</p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">gross minus recycled wins</p>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Currently at Risk</p>
            <p className="text-2xl font-bold tabular-nums mt-1 text-sky-600 dark:text-sky-400">{currency(openDeployed)}</p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">across {enrichedActive.length} open positions</p>
          </div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-xs text-gray-500 uppercase tracking-wider shrink-0">Filters</span>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 shrink-0">From</label>
          <input
            type="date"
            value={fromDate}
            onChange={e => setFromDate(e.target.value)}
            className="bg-gray-50 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm rounded px-2 py-1 focus:outline-none focus:border-gray-400 dark:focus:border-gray-500"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 shrink-0">To</label>
          <input
            type="date"
            value={toDate}
            onChange={e => setToDate(e.target.value)}
            className="bg-gray-50 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm rounded px-2 py-1 focus:outline-none focus:border-gray-400 dark:focus:border-gray-500"
          />
        </div>
        <select
          value={city}
          onChange={e => setCity(e.target.value)}
          className="bg-gray-50 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm rounded px-2 py-1 focus:outline-none focus:border-gray-400 dark:focus:border-gray-500"
        >
          <option value="">All Cities</option>
          {cities.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        {filtersActive && (
          <button
            onClick={() => { setFromDate(''); setToDate(''); setCity('') }}
            className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 underline"
          >
            Clear
          </button>
        )}
      </div>

      {/* Filtered summary */}
      <div>
        <p className="text-xs text-gray-400 dark:text-gray-600 uppercase tracking-wider mb-2 px-0.5">
          {filtersActive ? 'Filtered results' : 'Showing all trades'}
        </p>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">P&L</p>
            <p className={`text-2xl font-bold tabular-nums mt-1 ${filteredPnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
              {dollars(filteredPnl)}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">{filtersActive ? 'filtered trades' : 'all settled trades'}</p>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Win Rate</p>
            <p className="text-2xl font-bold tabular-nums mt-1 text-gray-900 dark:text-white">{filteredWinRate}</p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">{filteredWins}W · {filteredLosses}L</p>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Settled Trades</p>
            <p className="text-2xl font-bold tabular-nums mt-1 text-gray-900 dark:text-white">{filteredSettled.length}</p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">{filtersActive ? 'matching filters' : 'total resolved'}</p>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Capital Deployed</p>
            <p className="text-2xl font-bold tabular-nums mt-1 text-gray-900 dark:text-white">
              {filteredCapital > 0 ? currency(filteredCapital) : '—'}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">total dollars risked</p>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Return</p>
            <p className={`text-2xl font-bold tabular-nums mt-1 ${filteredReturn === null ? 'text-gray-400 dark:text-gray-600' : filteredReturn >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
              {filteredReturn === null
                ? '—'
                : `${filteredReturn >= 0 ? '+' : ''}${filteredReturn.toFixed(1)}%`}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">P&L ÷ capital deployed</p>
          </div>
        </div>
      </div>

      {/* Recent Results */}
      <Section title="Recent Results" shown={sortedSettled.length} total={enrichedSettled.length} className="bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-700">
        {sortedSettled.length === 0 ? (
          <Empty>
            {filtersActive
              ? 'No settled trades match the current filters.'
              : 'No settled trades yet — check back after markets resolve.'}
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800">
                  <ColHeader label="City"     tip="US city where the weather contract is settled"                                               sortKey="city"          sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Date"     tip="Date the high temperature is measured and the contract resolves"                             sortKey="targetDateStr" sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Strat"    tip="Which strategy version placed the bet. v1 = current edge-based logic."                       sortKey="strategy_version" sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Contract" tip="T = tail bet (above or below a threshold). B = bucket bet (temperature falls in a range)"   sortKey="typeCode"      sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Range"    tip="Temperature range the contract bets on. Bucket: midpoint ±1°F. Tail: threshold value."        sortKey="threshold"     sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Side"     tip="YES = we bet the condition is met. NO = we bet it is not"                                    sortKey="side"          sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Amount"   tip="Dollars staked on this trade (paper money in PAPER_TRADING mode)"                            sortKey="amount_usd"    sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Price"    tip="Price paid per contract (0–1 scale). 0.30 means 30 cents. Payout is $1 per contract if won"  sortKey="price_paid"    sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Our %"    tip="Our model's probability of YES at the moment of trade (GFS ensemble × calibration)"           sortKey="our_probability"    sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Mkt %"    tip="Market's implied probability of YES at the moment of trade (the YES ask price)"               sortKey="market_probability" sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Edge"     tip="Post-fee edge on the side we bet. YES: our %–mkt %–fee. NO: mkt %–our %–fee. Higher = stronger disagreement with market." sortKey="edge" sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="GFS"      tip="Which GFS forecast cycle (00z/06z/12z/18z) drove this bet. Reflects which cron run placed it." sortKey="gfs_run"       sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Result"   tip="Whether the market resolved in our favor"                                                    sortKey="result"        sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="P&L"      tip="Dollar profit (green) or loss (red) on this paper trade"                                    sortKey="pnl"           sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
                {sortedSettled.map(t => {
                  const won    = t.result === t.side
                  const pnlVal = parseFloat(t.pnl ?? '0')
                  return (
                    <tr key={t.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300">
                        <span className="flex items-center gap-1.5">
                          {t.city}
                          {t.isRain && <span className="text-xs font-medium px-1.5 py-0.5 rounded border bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800">RAIN</span>}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 tabular-nums text-xs">{t.dateDisplay}</td>
                      <td className="px-4 py-2.5">
                        {t.strategy_version ? (
                          <span className={`text-xs font-medium px-1.5 py-0.5 rounded border ${
                            t.strategy_version === 'v1'
                              ? 'bg-gray-50 dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700'
                              : 'bg-violet-50 dark:bg-violet-950 text-violet-600 dark:text-violet-400 border-violet-200 dark:border-violet-800'
                          }`}>
                            {t.strategy_version}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 font-mono text-xs tabular-nums">{t.typeCode}</td>
                      <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400 font-mono text-xs tabular-nums">{t.rangeDisplay || '—'}</td>
                      <td className="px-4 py-2.5">
                        <span className={`font-medium ${t.side === 'yes' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                          {t.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">{currency(t.amount_usd)}</td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">
                        {t.price_paid ? parseFloat(t.price_paid).toFixed(2) : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">{pct(t.our_probability)}</td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">{pct(t.market_probability)}</td>
                      <td className="px-4 py-2.5">
                        {t.edge !== null ? (
                          <span className={`tabular-nums font-mono text-xs font-medium ${t.edge >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                            {t.edge >= 0 ? '+' : ''}{(t.edge * 100).toFixed(1)}%
                          </span>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400 font-mono text-xs tabular-nums">{t.gfs_run || '—'}</td>
                      <td className="px-4 py-2.5">
                        {t.result ? (
                          <span className={`font-medium ${won ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                            {won ? 'WON' : 'LOST'}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`font-medium tabular-nums ${pnlVal >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                          {dollars(t.pnl)}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Active Positions */}
      <Section title="Active Positions" shown={sortedActive.length} total={enrichedActive.length} className="bg-sky-50 dark:bg-sky-900/30 border border-sky-200 dark:border-sky-700">
        {sortedActive.length === 0 ? (
          <Empty>{filtersActive ? 'No open positions match the current filters.' : 'No open positions.'}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800">
                  <ColHeader label="City"     tip="US city where the weather contract is settled"                                               sortKey="city"             sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Date"     tip="Date this contract resolves"                                                                 sortKey="targetDateStr"    sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Contract" tip="T = tail bet (above or below a threshold). B = bucket bet (temperature falls in a range)"   sortKey="typeCode"         sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Range"    tip="Temperature range the contract bets on. Bucket: midpoint ±1°F. Tail: threshold value."        sortKey="threshold"        sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Side"     tip="YES = we bet the condition is met. NO = we bet it is not"                                    sortKey="side"             sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Amount"   tip="Dollars staked on this open position (paper money in PAPER_TRADING mode)"                    sortKey="amount_usd"       sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Price"    tip="Price paid per contract (0–1 scale). 0.30 means 30 cents. Payout is $1 per contract if won"  sortKey="price_paid"       sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Our %"    tip="Our model's probability estimate using GFS ensemble weather forecasts (31 model runs)"       sortKey="our_probability"  sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Mkt %"    tip="The market's implied probability — the price other traders are paying for YES contracts"     sortKey="market_probability" sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Edge"     tip="Post-fee edge on the side we bet. YES: our %–mkt %–fee. NO: mkt %–our %–fee. Higher = stronger disagreement with market." sortKey="edge" sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
                {sortedActive.map(t => (
                  <tr key={t.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                    <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300">
                      <span className="flex items-center gap-1.5">
                        {t.city}
                        {t.isRain && <span className="text-xs font-medium px-1.5 py-0.5 rounded border bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800">RAIN</span>}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-500 tabular-nums text-xs">{t.dateDisplay}</td>
                    <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 font-mono text-xs tabular-nums">{t.typeCode}</td>
                    <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400 font-mono text-xs tabular-nums">{t.rangeDisplay || '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className={`font-medium ${t.side === 'yes' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                        {t.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">{currency(t.amount_usd)}</td>
                    <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">
                      {t.price_paid ? parseFloat(t.price_paid).toFixed(2) : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">{pct(t.our_probability)}</td>
                    <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">{pct(t.market_probability)}</td>
                    <td className="px-4 py-2.5">
                      {t.edge !== null ? (
                        <span className={`tabular-nums font-mono text-xs font-medium ${t.edge >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                          {t.edge >= 0 ? '+' : ''}{(t.edge * 100).toFixed(1)}%
                        </span>
                      ) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Signal Log */}
      <Section title="Signal Log" shown={sortedSignals.length} total={enrichedSignals.length} className="bg-violet-50 dark:bg-violet-900/30 border border-violet-200 dark:border-violet-700">
        {/* Toggle: actionable signals vs all evaluations (3-day window) */}
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-200 dark:border-gray-800 text-xs">
          <span className="text-gray-500 dark:text-gray-400 uppercase tracking-wider mr-1">Show</span>
          {([
            { v: 'actionable', label: 'Actionable only', desc: 'BET_YES/NO, SUSPICIOUS_EDGE, and NO_BET with a specific reason' },
            { v: 'all',        label: 'All evaluations', desc: 'Every market the bot looked at — including the boring NO_BET edge_too_low cases' },
          ] as const).map(opt => (
            <button
              key={opt.v}
              onClick={() => setSignalMode(opt.v)}
              title={opt.desc}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors border ${
                signalMode === opt.v
                  ? 'bg-gray-900 dark:bg-white text-white dark:text-gray-900 border-gray-900 dark:border-white'
                  : 'bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-600'
              }`}
            >
              {opt.label}
            </button>
          ))}
          <span className="text-gray-400 dark:text-gray-600 ml-auto">last 3 days</span>
        </div>
        {sortedSignals.length === 0 ? (
          <Empty>{filtersActive ? 'No signals match the current filters.' : (signalMode === 'actionable' ? 'No actionable signals in the last 3 days. Try "All evaluations".' : 'No signals logged yet.')}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800">
                  <ColHeader label="City"     tip="US city the bot evaluated"                                                                   sortKey="city"               sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Date"     tip="Target date of the contract being evaluated"                                                  sortKey="targetDateStr"      sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Contract" tip="T = tail bet (above or below a threshold). B = bucket bet (temperature falls in a range)"    sortKey="typeCode"           sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Our %"    tip="Our model's probability estimate using GFS ensemble weather forecasts (31 model runs)"        sortKey="our_probability"    sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Mkt %"    tip="The market's implied probability — the price other traders are paying for YES contracts"      sortKey="market_probability" sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Edge"     tip="Our % minus Market %. Positive = we think YES is underpriced (bet YES). Negative = bet NO"   sortKey="edge"               sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Action"   tip="BET_YES/NO = trade placed. NO_BET = edge too small. SUSPICIOUS_EDGE = edge too large (possible GFS model bias)" sortKey="action" sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
                {sortedSignals.map((s, i) => {
                  const edge = parseFloat(s.edge)
                  const actionStyle: Record<string, string> = {
                    BET_YES:         'bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800',
                    BET_NO:          'bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-400 border-red-200 dark:border-red-800',
                    NO_BET:          'bg-gray-100 dark:bg-gray-800 text-gray-500 border-gray-300 dark:border-gray-700',
                    SUSPICIOUS_EDGE: 'bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800',
                  }
                  const badgeCls = actionStyle[s.action] ?? 'bg-gray-100 dark:bg-gray-800 text-gray-500 border-gray-300 dark:border-gray-700'
                  return (
                    <tr key={i} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300">
                        <span className="flex items-center gap-1.5">
                          {s.city}
                          {s.isRain && <span className="text-xs font-medium px-1.5 py-0.5 rounded border bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800">RAIN</span>}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 tabular-nums text-xs">{s.dateDisplay}</td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 font-mono text-xs tabular-nums">{s.typeCode}</td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">{pct(s.our_probability)}</td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 tabular-nums font-mono text-xs">{pct(s.market_probability)}</td>
                      <td className="px-4 py-2.5">
                        <span className={`tabular-nums font-mono text-xs font-medium ${edge >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                          {edge >= 0 ? '+' : ''}{edge.toFixed(2)}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`text-xs font-medium px-2 py-0.5 rounded border ${badgeCls}`}>
                          {s.action}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <p className="text-center text-xs text-gray-400 dark:text-gray-700 pb-4">
        Refreshes every 5 min · All figures are paper trades
      </p>
    </main>
  )
}
