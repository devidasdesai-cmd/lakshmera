'use client'

import { useMemo, useState, useEffect } from 'react'
import Link from 'next/link'
import { Trade, parseTicker, dollars, currency } from '../../../lib/utils'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Props { trades: Trade[] }

interface ET {
  city:          string
  side:          string
  typeLabel:     string
  targetDateStr: string
  placedDate:    string
  leadDays:      number
  ourProb:       number
  mktProb:       number
  edge:          number
  pnl:           number
  amount:        number
  won:           boolean
  runLabel:      string  // e.g., "12z (11am CT)", "18z (5pm CT)", "Legacy (untagged)"
  strategy:      string  // 'v1' | 'v2'
  yesActual:     0 | 1   // for calibration plot — did contract resolve YES?
}

type StrategyFilter = 'all' | 'v1' | 'v2'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function runLabelFor(gfsRun: string | null): string {
  if (!gfsRun) return 'Legacy (untagged)'
  // Rain markets get a "rain_" prefix on the gfs_run field
  const isRain = gfsRun.startsWith('rain_')
  const cycle  = isRain ? gfsRun.slice(5) : gfsRun
  const cycleLabel: Record<string, string> = {
    '00z': '00z (11pm CT prev day)',
    '06z': '06z (~9am CT)',
    '12z': '12z (~11am CT)',
    '18z': '18z (~5pm CT)',
  }
  const label = cycleLabel[cycle] ?? cycle
  return isRain ? `Rain · ${label}` : label
}

function enrich(t: Trade): ET {
  const { city, typeCode, targetDateStr, targetDate } = parseTicker(t.ticker)
  const placedDate = t.created_at.slice(0, 10)
  const ourProb    = parseFloat(t.our_probability)
  const mktProb    = parseFloat(t.market_probability)
  const pnl        = parseFloat(t.pnl ?? '0')
  const amount     = parseFloat(t.amount_usd ?? '0')
  const won        = pnl > 0
  const edge       = t.side === 'yes' ? ourProb - mktProb : mktProb - ourProb
  const leadDays   = targetDate
    ? Math.max(0, Math.round(
        (new Date(targetDateStr + 'T00:00:00Z').getTime() -
         new Date(placedDate   + 'T00:00:00Z').getTime()) / 86400000
      ))
    : 0
  const typeLabel = typeCode.startsWith('B') ? 'Bucket' : 'Tail'
  const runLabel  = runLabelFor(t.gfs_run)
  const strategy = t.strategy_version ?? 'v1'
  // A trade "wins on YES" iff (the bet's side was YES AND it won) OR (side was NO AND it lost) — i.e., contract resolved YES.
  const yesActual: 0 | 1 = ((t.side === 'yes' && won) || (t.side === 'no' && !won)) ? 1 : 0
  return { city, side: t.side, typeLabel, targetDateStr, placedDate, leadDays, ourProb, mktProb, edge, pnl, amount, won, runLabel, strategy, yesActual }
}

function agg(ts: ET[]) {
  const wins    = ts.filter(t => t.won).length
  const pnl     = ts.reduce((s, t) => s + t.pnl,    0)
  const capital = ts.reduce((s, t) => s + t.amount,  0)
  return { count: ts.length, wins, losses: ts.length - wins, pnl, capital }
}

function groupBy<T>(arr: T[], key: (t: T) => string): Map<string, T[]> {
  const map = new Map<string, T[]>()
  for (const item of arr) {
    const k = key(item)
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(item)
  }
  return map
}

function edgeBucket(edge: number): string {
  if (edge < 0.10) return '5–10%'
  if (edge < 0.15) return '10–15%'
  if (edge < 0.20) return '15–20%'
  if (edge < 0.25) return '20–25%'
  return '25%+'
}

function mktBucket(mkt: number): string {
  if (mkt < 0.20) return '0–20%'
  if (mkt < 0.40) return '20–40%'
  if (mkt < 0.60) return '40–60%'
  if (mkt < 0.80) return '60–80%'
  return '80–100%'
}

function leadBucket(days: number): string {
  if (days <= 1) return '0–1 days'
  if (days <= 3) return '2–3 days'
  if (days <= 5) return '4–5 days'
  if (days <= 7) return '6–7 days'
  return '8+ days'
}

const EDGE_ORDER = ['5–10%', '10–15%', '15–20%', '20–25%', '25%+']
const MKT_ORDER  = ['0–20%', '20–40%', '40–60%', '60–80%', '80–100%']
const LEAD_ORDER = ['0–1 days', '2–3 days', '4–5 days', '6–7 days', '8+ days']

// ─── Sub-components ───────────────────────────────────────────────────────────

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">
      {children}
    </th>
  )
}

function Td({ children }: { children: React.ReactNode }) {
  return (
    <td className="px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300">
      {children}
    </td>
  )
}

function WinBar({ wins, total }: { wins: number; total: number }) {
  const rate  = total > 0 ? (wins / total) * 100 : 0
  const color = rate >= 60
    ? 'bg-emerald-500 dark:bg-emerald-400'
    : rate >= 45
    ? 'bg-amber-500 dark:bg-amber-400'
    : 'bg-red-500 dark:bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 shrink-0">
        <div className={`${color} h-1.5 rounded-full`} style={{ width: `${Math.min(rate, 100)}%` }} />
      </div>
      <span className="tabular-nums text-xs">{total > 0 ? `${rate.toFixed(0)}%` : '—'}</span>
    </div>
  )
}

function Pnl({ value }: { value: number }) {
  return (
    <span className={`tabular-nums font-medium ${value >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
      {dollars(value)}
    </span>
  )
}

type CalibBin = { mid: number; lo: number; hi: number; n: number; actual: number | null }

function CalibrationPlot({ v1, v2, strategyFilter }: {
  v1: CalibBin[]
  v2: CalibBin[]
  strategyFilter: StrategyFilter
}) {
  const W = 600, H = 320, PAD_L = 44, PAD_R = 16, PAD_T = 16, PAD_B = 36
  const PW = W - PAD_L - PAD_R
  const PH = H - PAD_T - PAD_B
  const xOf = (p: number) => PAD_L + p * PW
  const yOf = (p: number) => PAD_T + (1 - p) * PH
  const showV1 = strategyFilter === 'all' || strategyFilter === 'v1'
  const showV2 = strategyFilter === 'all' || strategyFilter === 'v2'

  function seriesPath(bins: CalibBin[]) {
    const pts = bins.filter(b => b.actual !== null).map(b => `${xOf(b.mid).toFixed(1)},${yOf(b.actual!).toFixed(1)}`)
    return pts.length ? `M ${pts.join(' L ')}` : ''
  }

  const v1HasData = v1.some(b => b.actual !== null)
  const v2HasData = v2.some(b => b.actual !== null)

  return (
    <div className="p-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" preserveAspectRatio="xMidYMid meet">
        {/* Axes */}
        <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + PH} className="stroke-gray-300 dark:stroke-gray-700" strokeWidth="1" />
        <line x1={PAD_L} y1={PAD_T + PH} x2={PAD_L + PW} y2={PAD_T + PH} className="stroke-gray-300 dark:stroke-gray-700" strokeWidth="1" />

        {/* Gridlines + tick labels (every 25%) */}
        {[0, 0.25, 0.5, 0.75, 1].map(t => (
          <g key={t}>
            <line x1={PAD_L} y1={yOf(t)} x2={PAD_L + PW} y2={yOf(t)} className="stroke-gray-200 dark:stroke-gray-800" strokeWidth="0.5" strokeDasharray="2,2" />
            <text x={PAD_L - 6} y={yOf(t) + 4} textAnchor="end" className="fill-gray-400 dark:fill-gray-600" fontSize="10">{Math.round(t * 100)}%</text>
            <line x1={xOf(t)} y1={PAD_T + PH} x2={xOf(t)} y2={PAD_T + PH + 4} className="stroke-gray-300 dark:stroke-gray-700" strokeWidth="1" />
            <text x={xOf(t)} y={PAD_T + PH + 18} textAnchor="middle" className="fill-gray-400 dark:fill-gray-600" fontSize="10">{Math.round(t * 100)}%</text>
          </g>
        ))}

        {/* Perfect-calibration diagonal */}
        <line x1={xOf(0)} y1={yOf(0)} x2={xOf(1)} y2={yOf(1)} className="stroke-gray-400 dark:stroke-gray-600" strokeWidth="1" strokeDasharray="4,3" />

        {/* V1 series — gray */}
        {showV1 && v1HasData && (
          <>
            <path d={seriesPath(v1)} fill="none" className="stroke-gray-500 dark:stroke-gray-400" strokeWidth="1.5" />
            {v1.filter(b => b.actual !== null).map((b, i) => (
              <circle key={`v1-${i}`} cx={xOf(b.mid)} cy={yOf(b.actual!)} r={Math.min(8, 2 + Math.sqrt(b.n))} className="fill-gray-500 dark:fill-gray-400" opacity="0.7">
                <title>{`V1 · predicted ${Math.round(b.lo * 100)}-${Math.round(b.hi * 100)}% · actual ${(b.actual! * 100).toFixed(1)}% · N=${b.n}`}</title>
              </circle>
            ))}
          </>
        )}

        {/* V2 series — violet (matches dashboard pill color) */}
        {showV2 && v2HasData && (
          <>
            <path d={seriesPath(v2)} fill="none" className="stroke-violet-500" strokeWidth="2" />
            {v2.filter(b => b.actual !== null).map((b, i) => (
              <circle key={`v2-${i}`} cx={xOf(b.mid)} cy={yOf(b.actual!)} r={Math.min(8, 2 + Math.sqrt(b.n))} className="fill-violet-500" opacity="0.85">
                <title>{`V2 · predicted ${Math.round(b.lo * 100)}-${Math.round(b.hi * 100)}% · actual ${(b.actual! * 100).toFixed(1)}% · N=${b.n}`}</title>
              </circle>
            ))}
          </>
        )}

        {/* Axis labels */}
        <text x={PAD_L + PW / 2} y={H - 4} textAnchor="middle" className="fill-gray-500 dark:fill-gray-400" fontSize="11">Predicted YES probability</text>
        <text x={12} y={PAD_T + PH / 2} textAnchor="middle" transform={`rotate(-90, 12, ${PAD_T + PH / 2})`} className="fill-gray-500 dark:fill-gray-400" fontSize="11">Actual YES rate</text>
      </svg>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400 mt-2 px-2">
        {showV1 && (
          <span className="flex items-center gap-1.5">
            <svg width="20" height="8"><line x1="0" y1="4" x2="20" y2="4" className="stroke-gray-500 dark:stroke-gray-400" strokeWidth="1.5"/></svg>
            V1 ({v1.reduce((s, b) => s + b.n, 0)} trades)
          </span>
        )}
        {showV2 && (
          <span className="flex items-center gap-1.5">
            <svg width="20" height="8"><line x1="0" y1="4" x2="20" y2="4" className="stroke-violet-500" strokeWidth="2"/></svg>
            V2 ({v2.reduce((s, b) => s + b.n, 0)} trades)
          </span>
        )}
        <span className="flex items-center gap-1.5">
          <svg width="20" height="8"><line x1="0" y1="4" x2="20" y2="4" className="stroke-gray-400 dark:stroke-gray-600" strokeWidth="1" strokeDasharray="3,2"/></svg>
          perfect calibration
        </span>
        <span className="ml-auto text-xs italic">
          Closer to the dashed diagonal = better calibrated. Dot size = sample count.
        </span>
      </div>
    </div>
  )
}

function AnalyticsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800">
        <h2 className="text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        {children}
      </div>
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function AnalyticsDashboard({ trades }: Props) {

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

  const [strategyFilter, setStrategyFilter] = useState<StrategyFilter>('all')

  const allData = useMemo(() => trades.map(enrich), [trades])
  const data = useMemo(
    () => strategyFilter === 'all' ? allData : allData.filter(t => t.strategy === strategyFilter),
    [allData, strategyFilter]
  )

  // V1 vs V2 counts for the toggle labels
  const v1Count = useMemo(() => allData.filter(t => t.strategy === 'v1').length, [allData])
  const v2Count = useMemo(() => allData.filter(t => t.strategy === 'v2').length, [allData])

  // 1 — Day-by-Day P&L (by resolution date)
  const dayByDay = useMemo(() => {
    const grouped = groupBy(data, t => t.targetDateStr)
    const dates   = Array.from(grouped.keys()).filter(Boolean).sort()
    let cumulPnl = 0, cumulWins = 0, cumulCount = 0
    return dates.map(date => {
      const s = agg(grouped.get(date)!)
      cumulPnl   += s.pnl
      cumulWins  += s.wins
      cumulCount += s.count
      return { date, ...s, cumulPnl, cumulWins, cumulCount }
    })
  }, [data])

  // 2 — By City
  const byCity = useMemo(() => {
    const grouped = groupBy(data, t => t.city)
    return Array.from(grouped.entries())
      .map(([city, ts]) => ({ city, ...agg(ts) }))
      .sort((a, b) => b.pnl - a.pnl)
  }, [data])

  // 3 — By Contract Type
  const byType = useMemo(() => {
    const grouped = groupBy(data, t => t.typeLabel)
    return Array.from(grouped.entries())
      .map(([label, ts]) => ({ label, ...agg(ts) }))
      .sort((a, b) => b.count - a.count)
  }, [data])

  // 4 — By Side
  const bySide = useMemo(() => {
    const grouped = groupBy(data, t => t.side === 'yes' ? 'YES' : 'NO')
    return Array.from(grouped.entries())
      .map(([label, ts]) => ({ label, ...agg(ts) }))
      .sort((a, b) => b.count - a.count)
  }, [data])

  // 4b — By GFS Run (which cron cycle placed the bet)
  const byRun = useMemo(() => {
    const grouped = groupBy(data, t => t.runLabel)
    // Sort by canonical run order: 00z, 06z, 12z, 18z, then Rain variants, then Legacy
    const runOrder = (label: string): number => {
      if (label.startsWith('Legacy')) return 99
      if (label.startsWith('Rain')) return 50 + (label.includes('00z') ? 0 : label.includes('06z') ? 1 : label.includes('12z') ? 2 : 3)
      if (label.startsWith('00z')) return 0
      if (label.startsWith('06z')) return 1
      if (label.startsWith('12z')) return 2
      if (label.startsWith('18z')) return 3
      return 100
    }
    return Array.from(grouped.entries())
      .map(([label, ts]) => ({ label, ...agg(ts) }))
      .sort((a, b) => runOrder(a.label) - runOrder(b.label))
  }, [data])

  // 5 — Edge vs Outcome
  const byEdge = useMemo(() => {
    const grouped = groupBy(data, t => edgeBucket(t.edge))
    return EDGE_ORDER
      .filter(k => grouped.has(k))
      .map(label => {
        const s = agg(grouped.get(label)!)
        return { label, ...s, avgPnl: s.count > 0 ? s.pnl / s.count : 0 }
      })
  }, [data])

  // 6 — Market Price Bucket
  const byMkt = useMemo(() => {
    const grouped = groupBy(data, t => mktBucket(t.mktProb))
    return MKT_ORDER
      .filter(k => grouped.has(k))
      .map(label => ({ label, ...agg(grouped.get(label)!) }))
  }, [data])

  // 7 — Lead Time
  const byLead = useMemo(() => {
    const grouped = groupBy(data, t => leadBucket(t.leadDays))
    return LEAD_ORDER
      .filter(k => grouped.has(k))
      .map(label => ({ label, ...agg(grouped.get(label)!) }))
  }, [data])

  // 8a — Calibration (predicted YES prob vs actual YES rate, binned). Always uses
  // allData (not strategy-filtered) so V1 vs V2 can be overlaid; the chart toggles
  // which series to show based on strategyFilter.
  const calibration = useMemo(() => {
    const bins = [
      [0.00, 0.05], [0.05, 0.10], [0.10, 0.15], [0.15, 0.20],
      [0.20, 0.30], [0.30, 0.40], [0.40, 0.50], [0.50, 0.70], [0.70, 1.01],
    ] as const
    function bin(rows: ET[]) {
      return bins.map(([lo, hi]) => {
        const sub = rows.filter(r => r.ourProb >= lo && r.ourProb < hi)
        const actual = sub.length ? sub.reduce((s, r) => s + r.yesActual, 0) / sub.length : null
        return { mid: (lo + hi) / 2, lo, hi, n: sub.length, actual }
      })
    }
    return {
      v1: bin(allData.filter(t => t.strategy === 'v1')),
      v2: bin(allData.filter(t => t.strategy === 'v2')),
    }
  }, [allData])

  // 8 — Running Win Rate (by bet placement date)
  const running = useMemo(() => {
    const grouped = groupBy(data, t => t.placedDate)
    const dates   = Array.from(grouped.keys()).filter(Boolean).sort()
    let cumulCount = 0, cumulWins = 0, cumulPnl = 0
    return dates.map(date => {
      const s = agg(grouped.get(date)!)
      cumulCount += s.count
      cumulWins  += s.wins
      cumulPnl   += s.pnl
      return { date, dailyCount: s.count, cumulCount, cumulWins, cumulPnl }
    })
  }, [data])

  if (data.length === 0) {
    return (
      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <p className="text-gray-500 text-center py-20">No settled trades to analyze yet.</p>
      </main>
    )
  }

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link href="/" className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors">
            ← Dashboard
          </Link>
          <h1 className="text-xl font-bold tracking-tight text-gray-900 dark:text-white mt-1">ANALYTICS</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {data.length} settled trades
            {strategyFilter !== 'all' && <span className="text-gray-400 dark:text-gray-600"> (filtered to {strategyFilter})</span>}
          </p>
        </div>
        <button
          onClick={toggleTheme}
          aria-label="Toggle light/dark mode"
          className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 transition-colors mt-1"
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
      </div>

      {/* Strategy filter */}
      <div className="flex items-center gap-2 text-sm">
        <span className="text-xs text-gray-500 uppercase tracking-wider mr-1">Strategy</span>
        {([
          { v: 'all', label: `All (${allData.length})` },
          { v: 'v1',  label: `V1 (${v1Count})` },
          { v: 'v2',  label: `V2 (${v2Count})` },
        ] as { v: StrategyFilter; label: string }[]).map(opt => (
          <button
            key={opt.v}
            onClick={() => setStrategyFilter(opt.v)}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors border ${
              strategyFilter === opt.v
                ? 'bg-gray-900 dark:bg-white text-white dark:text-gray-900 border-gray-900 dark:border-white'
                : 'bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-600'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Calibration plot — always shows both V1 and V2 overlaid (independent of filter) */}
      <AnalyticsSection title="Calibration — Predicted YES probability vs actual YES rate">
        <CalibrationPlot v1={calibration.v1} v2={calibration.v2} strategyFilter={strategyFilter} />
      </AnalyticsSection>

      {/* 1 — Day-by-Day P&L */}
      <AnalyticsSection title="Day-by-Day P&L (by Resolution Date)">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800">
              <Th>Date</Th><Th>Trades</Th><Th>W / L</Th><Th>Win Rate</Th><Th>Daily P&L</Th><Th>Cumulative P&L</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
            {dayByDay.map(r => (
              <tr key={r.date} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                <Td>{r.date}</Td>
                <Td>{r.count}</Td>
                <Td>{r.wins}W · {r.losses}L</Td>
                <Td><WinBar wins={r.wins} total={r.count} /></Td>
                <Td><Pnl value={r.pnl} /></Td>
                <Td><Pnl value={r.cumulPnl} /></Td>
              </tr>
            ))}
          </tbody>
        </table>
      </AnalyticsSection>

      {/* 2 — By City */}
      <AnalyticsSection title="Performance by City">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800">
              <Th>City</Th><Th>Trades</Th><Th>W / L</Th><Th>Win Rate</Th><Th>P&L</Th><Th>Capital</Th><Th>Return</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
            {byCity.map(r => {
              const ret = r.capital > 0 ? (r.pnl / r.capital) * 100 : null
              return (
                <tr key={r.city} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                  <Td>{r.city}</Td>
                  <Td>{r.count}</Td>
                  <Td>{r.wins}W · {r.losses}L</Td>
                  <Td><WinBar wins={r.wins} total={r.count} /></Td>
                  <Td><Pnl value={r.pnl} /></Td>
                  <Td><span className="tabular-nums text-gray-500">{currency(r.capital)}</span></Td>
                  <Td>
                    {ret === null ? '—' : (
                      <span className={`tabular-nums font-medium ${ret >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                        {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
                      </span>
                    )}
                  </Td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </AnalyticsSection>

      {/* 3 & 4 — Contract Type and Side side-by-side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

        <AnalyticsSection title="Performance by Contract Type">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-800">
                <Th>Type</Th><Th>Trades</Th><Th>W / L</Th><Th>Win Rate</Th><Th>P&L</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
              {byType.map(r => (
                <tr key={r.label} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                  <Td>{r.label}</Td>
                  <Td>{r.count}</Td>
                  <Td>{r.wins}W · {r.losses}L</Td>
                  <Td><WinBar wins={r.wins} total={r.count} /></Td>
                  <Td><Pnl value={r.pnl} /></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </AnalyticsSection>

        <AnalyticsSection title="Performance by Side">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-800">
                <Th>Side</Th><Th>Trades</Th><Th>W / L</Th><Th>Win Rate</Th><Th>P&L</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
              {bySide.map(r => (
                <tr key={r.label} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                  <Td>
                    <span className={`font-medium ${r.label === 'YES' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                      {r.label}
                    </span>
                  </Td>
                  <Td>{r.count}</Td>
                  <Td>{r.wins}W · {r.losses}L</Td>
                  <Td><WinBar wins={r.wins} total={r.count} /></Td>
                  <Td><Pnl value={r.pnl} /></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </AnalyticsSection>
      </div>

      {/* 4b — By GFS Run / Cron Cycle */}
      <AnalyticsSection title="Performance by Bot Run (GFS Cycle)">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800">
              <Th>Run</Th><Th>Trades</Th><Th>W / L</Th><Th>Win Rate</Th><Th>P&L</Th><Th>Capital</Th><Th>Return</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
            {byRun.map(r => {
              const ret = r.capital > 0 ? (r.pnl / r.capital) * 100 : null
              return (
                <tr key={r.label} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                  <Td><span className="font-mono text-xs">{r.label}</span></Td>
                  <Td>{r.count}</Td>
                  <Td>{r.wins}W · {r.losses}L</Td>
                  <Td><WinBar wins={r.wins} total={r.count} /></Td>
                  <Td><Pnl value={r.pnl} /></Td>
                  <Td><span className="tabular-nums text-gray-500">{currency(r.capital)}</span></Td>
                  <Td>
                    {ret === null ? '—' : (
                      <span className={`tabular-nums font-medium ${ret >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                        {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
                      </span>
                    )}
                  </Td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </AnalyticsSection>

      {/* 5 — Edge vs Outcome */}
      <AnalyticsSection title="Edge vs Outcome">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800">
              <Th>Edge Range</Th><Th>Trades</Th><Th>W / L</Th><Th>Win Rate</Th><Th>Total P&L</Th><Th>Avg P&L / Trade</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
            {byEdge.map(r => (
              <tr key={r.label} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                <Td>{r.label}</Td>
                <Td>{r.count}</Td>
                <Td>{r.wins}W · {r.losses}L</Td>
                <Td><WinBar wins={r.wins} total={r.count} /></Td>
                <Td><Pnl value={r.pnl} /></Td>
                <Td><Pnl value={r.avgPnl} /></Td>
              </tr>
            ))}
          </tbody>
        </table>
      </AnalyticsSection>

      {/* 6 — Market Price Bucket */}
      <AnalyticsSection title="Win Rate by Market YES Price">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800">
              <Th>YES Ask Price</Th><Th>Trades</Th><Th>W / L</Th><Th>Win Rate</Th><Th>P&L</Th><Th>Capital</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
            {byMkt.map(r => (
              <tr key={r.label} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                <Td>{r.label}</Td>
                <Td>{r.count}</Td>
                <Td>{r.wins}W · {r.losses}L</Td>
                <Td><WinBar wins={r.wins} total={r.count} /></Td>
                <Td><Pnl value={r.pnl} /></Td>
                <Td><span className="tabular-nums text-gray-500">{currency(r.capital)}</span></Td>
              </tr>
            ))}
          </tbody>
        </table>
      </AnalyticsSection>

      {/* 7 — Lead Time */}
      <AnalyticsSection title="Performance by Days Until Settlement">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800">
              <Th>Days Out</Th><Th>Trades</Th><Th>W / L</Th><Th>Win Rate</Th><Th>P&L</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
            {byLead.map(r => (
              <tr key={r.label} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                <Td>{r.label}</Td>
                <Td>{r.count}</Td>
                <Td>{r.wins}W · {r.losses}L</Td>
                <Td><WinBar wins={r.wins} total={r.count} /></Td>
                <Td><Pnl value={r.pnl} /></Td>
              </tr>
            ))}
          </tbody>
        </table>
      </AnalyticsSection>

      {/* 8 — Running Win Rate */}
      <AnalyticsSection title="Running Win Rate (by Bet Placement Date)">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800">
              <Th>Date</Th><Th>Daily Bets</Th><Th>Cumul. Trades</Th><Th>Cumul. Wins</Th><Th>Cumul. Win Rate</Th><Th>Cumul. P&L</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800/60">
            {running.map(r => (
              <tr key={r.date} className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
                <Td>{r.date}</Td>
                <Td>{r.dailyCount}</Td>
                <Td>{r.cumulCount}</Td>
                <Td>{r.cumulWins}</Td>
                <Td><WinBar wins={r.cumulWins} total={r.cumulCount} /></Td>
                <Td><Pnl value={r.cumulPnl} /></Td>
              </tr>
            ))}
          </tbody>
        </table>
      </AnalyticsSection>

      <p className="text-center text-xs text-gray-400 dark:text-gray-700 pb-4">
        Settled paper trades only · Refreshes every page load
      </p>
    </main>
  )
}
