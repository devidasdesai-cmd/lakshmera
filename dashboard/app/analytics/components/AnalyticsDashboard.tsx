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
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

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
  return { city, side: t.side, typeLabel, targetDateStr, placedDate, leadDays, ourProb, mktProb, edge, pnl, amount, won }
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

  const data = useMemo(() => trades.map(enrich), [trades])

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
          <p className="text-sm text-gray-500 mt-0.5">{data.length} settled trades</p>
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
