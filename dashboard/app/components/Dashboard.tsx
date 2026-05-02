'use client'

import { useState, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { Trade, Signal, parseTicker, pct, dollars, SERIES_TO_CITY } from '../../lib/utils'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Props {
  settled: Trade[]
  active:  Trade[]
  signals: Signal[]
}

type SortDir   = 'asc' | 'desc'
type SortState = { col: string; dir: SortDir }

interface EnrichedTrade extends Trade {
  city:          string
  dateDisplay:   string
  typeCode:      string
  targetDateStr: string
}

interface EnrichedSignal extends Signal {
  dateDisplay:   string
  typeCode:      string
  targetDateStr: string
}

// ─── Enrichment ──────────────────────────────────────────────────────────────

function enrichTrade(t: Trade): EnrichedTrade {
  const { city, dateDisplay, typeCode, targetDateStr } = parseTicker(t.ticker)
  return { ...t, city, dateDisplay, typeCode, targetDateStr }
}

function enrichSignal(s: Signal): EnrichedSignal {
  const { dateDisplay, typeCode, targetDateStr } = parseTicker(s.ticker)
  return { ...s, dateDisplay, typeCode, targetDateStr }
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
          ${active ? 'text-gray-200 border-gray-400' : 'text-gray-500 border-gray-700 hover:text-gray-300'}`}>
          {label}
        </span>
        <span className="text-xs text-gray-600">
          {active ? (sort.dir === 'asc' ? '↑' : '↓') : '↕'}
        </span>
      </button>

      {tipPos && createPortal(
        <div
          className="fixed z-50 w-56 bg-gray-800 border border-gray-700 rounded-lg p-2.5
            text-xs text-gray-300 shadow-xl pointer-events-none leading-relaxed"
          style={{ left: tipPos.x, top: tipPos.y }}
        >
          {tip}
        </div>,
        document.body
      )}
    </th>
  )
}

function Section({ title, shown, total, children }: {
  title:    string
  shown:    number
  total:    number
  children: React.ReactNode
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{title}</h2>
        <span className="text-xs text-gray-600">
          {shown < total ? `${shown} of ${total}` : `${total} rows`}
        </span>
      </div>
      {children}
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-10 text-center text-sm text-gray-600">{children}</div>
}

function StatCard({ label, value, valueClass, sub }: {
  label:      string
  value:      string
  valueClass: string
  sub:        string
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold tabular-nums mt-1 ${valueClass}`}>{value}</p>
      <p className="text-xs text-gray-600 mt-1">{sub}</p>
    </div>
  )
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export default function Dashboard({ settled, active, signals }: Props) {

  // Filter state
  const [fromDate, setFromDate] = useState('')
  const [toDate,   setToDate]   = useState('')
  const [city,     setCity]     = useState('')

  // Sort state (independent per table)
  const [settledSort, setSettledSort] = useState<SortState>({ col: 'targetDateStr', dir: 'desc' })
  const [activeSort,  setActiveSort]  = useState<SortState>({ col: 'targetDateStr', dir: 'asc'  })
  const [signalSort,  setSignalSort]  = useState<SortState>({ col: 'targetDateStr', dir: 'desc' })

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
  const filteredSignals = useMemo(() => applyFilters(enrichedSignals), [enrichedSignals, fromDate, toDate, city])

  const sortedSettled = useMemo(() => applySort(filteredSettled, settledSort), [filteredSettled, settledSort])
  const sortedActive  = useMemo(() => applySort(filteredActive,  activeSort),  [filteredActive,  activeSort])
  const sortedSignals = useMemo(() => applySort(filteredSignals, signalSort),  [filteredSignals, signalSort])

  // All-time stats (unfiltered)
  const totalPnl    = enrichedSettled.reduce((s, t) => s + parseFloat(t.pnl ?? '0'), 0)
  const wins        = enrichedSettled.filter(t => parseFloat(t.pnl ?? '0') > 0).length
  const losses      = enrichedSettled.filter(t => parseFloat(t.pnl ?? '0') <= 0).length
  const winRate     = enrichedSettled.length > 0
    ? `${(wins / enrichedSettled.length * 100).toFixed(1)}%`
    : '—'

  const filtersActive = !!(fromDate || toDate || city)

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">LAKSHMERA</h1>
          <p className="text-sm text-gray-500 mt-0.5">Weather Prediction Market Bot</p>
        </div>
        <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-950 text-amber-400 border border-amber-800 mt-1">
          PAPER TRADING
        </span>
      </div>

      {/* Stats — always all-time, never filtered */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Total P&L"
          value={dollars(totalPnl)}
          valueClass={totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}
          sub="all-time paper trades"
        />
        <StatCard
          label="Win Rate"
          value={winRate}
          valueClass="text-white"
          sub={`${wins}W · ${losses}L`}
        />
        <StatCard
          label="Open Positions"
          value={String(enrichedActive.length)}
          valueClass="text-sky-400"
          sub="pending settlement"
        />
        <StatCard
          label="Settled Trades"
          value={String(enrichedSettled.length)}
          valueClass="text-white"
          sub="total resolved"
        />
      </div>

      {/* Filter bar */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-xs text-gray-500 uppercase tracking-wider shrink-0">Filters</span>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 shrink-0">From</label>
          <input
            type="date"
            value={fromDate}
            onChange={e => setFromDate(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded px-2 py-1 focus:outline-none focus:border-gray-500"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 shrink-0">To</label>
          <input
            type="date"
            value={toDate}
            onChange={e => setToDate(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded px-2 py-1 focus:outline-none focus:border-gray-500"
          />
        </div>
        <select
          value={city}
          onChange={e => setCity(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded px-2 py-1 focus:outline-none focus:border-gray-500"
        >
          <option value="">All Cities</option>
          {cities.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        {filtersActive && (
          <button
            onClick={() => { setFromDate(''); setToDate(''); setCity('') }}
            className="text-xs text-gray-500 hover:text-gray-300 underline"
          >
            Clear
          </button>
        )}
        <span className="text-xs text-gray-700 ml-auto hidden sm:block">
          Summary cards always show all-time totals
        </span>
      </div>

      {/* Recent Results */}
      <Section title="Recent Results" shown={sortedSettled.length} total={enrichedSettled.length}>
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
                <tr className="border-b border-gray-800">
                  <ColHeader label="City"     tip="US city where the weather contract is settled"                                               sortKey="city"          sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Date"     tip="Date the high temperature is measured and the contract resolves"                             sortKey="targetDateStr" sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Contract" tip="T = tail bet (above or below a threshold). B = bucket bet (temperature falls in a range)"   sortKey="typeCode"      sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Side"     tip="YES = we bet the condition is met. NO = we bet it is not"                                    sortKey="side"          sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Price"    tip="Price paid per contract (0–1 scale). 0.30 means 30 cents. Payout is $1 per contract if won"  sortKey="price_paid"    sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="Result"   tip="Whether the market resolved in our favor"                                                    sortKey="result"        sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                  <ColHeader label="P&L"      tip="Dollar profit (green) or loss (red) on this paper trade"                                    sortKey="pnl"           sort={settledSort} onSort={k => setSettledSort(toggleSort(settledSort, k))} />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {sortedSettled.map(t => {
                  const won    = t.result === t.side
                  const pnlVal = parseFloat(t.pnl ?? '0')
                  return (
                    <tr key={t.id} className="hover:bg-gray-800/40 transition-colors">
                      <td className="px-4 py-2.5 text-gray-300">{t.city}</td>
                      <td className="px-4 py-2.5 text-gray-500 tabular-nums text-xs">{t.dateDisplay}</td>
                      <td className="px-4 py-2.5 text-gray-300 font-mono text-xs tabular-nums">{t.typeCode}</td>
                      <td className="px-4 py-2.5">
                        <span className={`font-medium ${t.side === 'yes' ? 'text-emerald-400' : 'text-red-400'}`}>
                          {t.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-300 tabular-nums font-mono text-xs">
                        {t.price_paid ? parseFloat(t.price_paid).toFixed(2) : '—'}
                      </td>
                      <td className="px-4 py-2.5">
                        {t.result ? (
                          <span className={`font-medium ${won ? 'text-emerald-400' : 'text-red-400'}`}>
                            {won ? 'WON' : 'LOST'}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`font-medium tabular-nums ${pnlVal >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
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
      <Section title="Active Positions" shown={sortedActive.length} total={enrichedActive.length}>
        {sortedActive.length === 0 ? (
          <Empty>{filtersActive ? 'No open positions match the current filters.' : 'No open positions.'}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <ColHeader label="City"     tip="US city where the weather contract is settled"                                               sortKey="city"             sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Date"     tip="Date this contract resolves"                                                                 sortKey="targetDateStr"    sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Contract" tip="T = tail bet (above or below a threshold). B = bucket bet (temperature falls in a range)"   sortKey="typeCode"         sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Side"     tip="YES = we bet the condition is met. NO = we bet it is not"                                    sortKey="side"             sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Price"    tip="Price paid per contract (0–1 scale). 0.30 means 30 cents. Payout is $1 per contract if won"  sortKey="price_paid"       sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Our %"    tip="Our model's probability estimate using GFS ensemble weather forecasts (31 model runs)"       sortKey="our_probability"  sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                  <ColHeader label="Mkt %"    tip="The market's implied probability — the price other traders are paying for YES contracts"     sortKey="market_probability" sort={activeSort} onSort={k => setActiveSort(toggleSort(activeSort, k))} />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {sortedActive.map(t => (
                  <tr key={t.id} className="hover:bg-gray-800/40 transition-colors">
                    <td className="px-4 py-2.5 text-gray-300">{t.city}</td>
                    <td className="px-4 py-2.5 text-gray-500 tabular-nums text-xs">{t.dateDisplay}</td>
                    <td className="px-4 py-2.5 text-gray-300 font-mono text-xs tabular-nums">{t.typeCode}</td>
                    <td className="px-4 py-2.5">
                      <span className={`font-medium ${t.side === 'yes' ? 'text-emerald-400' : 'text-red-400'}`}>
                        {t.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-300 tabular-nums font-mono text-xs">
                      {t.price_paid ? parseFloat(t.price_paid).toFixed(2) : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-gray-300 tabular-nums font-mono text-xs">{pct(t.our_probability)}</td>
                    <td className="px-4 py-2.5 text-gray-300 tabular-nums font-mono text-xs">{pct(t.market_probability)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Signal Log */}
      <Section title="Signal Log" shown={sortedSignals.length} total={enrichedSignals.length}>
        {sortedSignals.length === 0 ? (
          <Empty>{filtersActive ? 'No signals match the current filters.' : 'No signals logged yet.'}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <ColHeader label="City"     tip="US city the bot evaluated"                                                                   sortKey="city"               sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Date"     tip="Target date of the contract being evaluated"                                                  sortKey="targetDateStr"      sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Contract" tip="T = tail bet (above or below a threshold). B = bucket bet (temperature falls in a range)"    sortKey="typeCode"           sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Our %"    tip="Our model's probability estimate using GFS ensemble weather forecasts (31 model runs)"        sortKey="our_probability"    sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Mkt %"    tip="The market's implied probability — the price other traders are paying for YES contracts"      sortKey="market_probability" sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Edge"     tip="Our % minus Market %. Positive = we think YES is underpriced (bet YES). Negative = bet NO"   sortKey="edge"               sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                  <ColHeader label="Action"   tip="BET_YES/NO = trade placed. NO_BET = edge too small. SUSPICIOUS_EDGE = edge too large (possible GFS model bias)" sortKey="action" sort={signalSort} onSort={k => setSignalSort(toggleSort(signalSort, k))} />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {sortedSignals.map((s, i) => {
                  const edge = parseFloat(s.edge)
                  const actionStyle: Record<string, string> = {
                    BET_YES:         'bg-emerald-950 text-emerald-400 border-emerald-800',
                    BET_NO:          'bg-red-950 text-red-400 border-red-800',
                    NO_BET:          'bg-gray-800 text-gray-500 border-gray-700',
                    SUSPICIOUS_EDGE: 'bg-amber-950 text-amber-400 border-amber-800',
                  }
                  const badgeCls = actionStyle[s.action] ?? 'bg-gray-800 text-gray-400 border-gray-700'
                  return (
                    <tr key={i} className="hover:bg-gray-800/40 transition-colors">
                      <td className="px-4 py-2.5 text-gray-300">{s.city}</td>
                      <td className="px-4 py-2.5 text-gray-500 tabular-nums text-xs">{s.dateDisplay}</td>
                      <td className="px-4 py-2.5 text-gray-300 font-mono text-xs tabular-nums">{s.typeCode}</td>
                      <td className="px-4 py-2.5 text-gray-300 tabular-nums font-mono text-xs">{pct(s.our_probability)}</td>
                      <td className="px-4 py-2.5 text-gray-300 tabular-nums font-mono text-xs">{pct(s.market_probability)}</td>
                      <td className="px-4 py-2.5">
                        <span className={`tabular-nums font-mono text-xs font-medium ${edge >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
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

      <p className="text-center text-xs text-gray-700 pb-4">
        Refreshes every 5 min · All figures are paper trades
      </p>
    </main>
  )
}
