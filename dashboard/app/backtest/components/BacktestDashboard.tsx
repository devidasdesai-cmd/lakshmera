'use client'

import { useState } from 'react'
import Link from 'next/link'
import { BacktestTrade, parseTicker, pct, dollars } from '../../../lib/utils'

interface Props {
  trades: BacktestTrade[]
  runIds: string[]
}

const ACTION_STYLE: Record<string, string> = {
  BET_YES:        'bg-green-900 text-green-300',
  BET_NO:         'bg-red-900 text-red-300',
  NO_BET:         'bg-gray-800 text-gray-400',
  SUSPICIOUS_EDGE:'bg-yellow-900 text-yellow-300',
}

const RESULT_STYLE: Record<string, string> = {
  yes: 'text-green-400',
  no:  'text-red-400',
}

type SortKey = 'target_date' | 'city' | 'edge' | 'pnl'
type SortDir = 'asc' | 'desc'

export default function BacktestDashboard({ trades, runIds }: Props) {
  const [selectedRun, setSelectedRun] = useState(runIds[0] ?? '')
  const [showBetsOnly, setShowBetsOnly] = useState(false)
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: 'target_date', dir: 'desc' })

  const runTrades = trades.filter(t => t.run_id === selectedRun)
  const betTrades = runTrades.filter(t => t.action === 'BET_YES' || t.action === 'BET_NO')
  const wins = betTrades.filter(t => t.pnl !== null && parseFloat(t.pnl) > 0).length
  const totalPnl = betTrades.reduce((s, t) => s + (t.pnl ? parseFloat(t.pnl) : 0), 0)
  const winRate = betTrades.length > 0 ? `${Math.round(wins / betTrades.length * 100)}%` : '—'

  const displayed = (showBetsOnly ? betTrades : runTrades).slice().sort((a, b) => {
    let av: string | number = 0, bv: string | number = 0
    if (sort.key === 'target_date') { av = a.target_date ?? ''; bv = b.target_date ?? '' }
    if (sort.key === 'city')        { av = a.city ?? '';        bv = b.city ?? '' }
    if (sort.key === 'edge')        { av = parseFloat(a.edge);  bv = parseFloat(b.edge) }
    if (sort.key === 'pnl')         { av = a.pnl ? parseFloat(a.pnl) : -Infinity; bv = b.pnl ? parseFloat(b.pnl) : -Infinity }
    if (av < bv) return sort.dir === 'asc' ? -1 : 1
    if (av > bv) return sort.dir === 'asc' ? 1 : -1
    return 0
  })

  function toggleSort(key: SortKey) {
    setSort(s => s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' })
  }

  function sortIcon(key: SortKey) {
    if (sort.key !== key) return <span className="ml-1 text-gray-600">↕</span>
    return <span className="ml-1 text-blue-400">{sort.dir === 'asc' ? '↑' : '↓'}</span>
  }

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Backtest Results</h1>
            <p className="text-sm text-gray-400 mt-0.5">
              Simulated trades against settled Kalshi contracts using historical GFS forecasts
            </p>
          </div>
          <div className="flex items-center gap-3">
            {runIds.length > 0 && (
              <select
                value={selectedRun}
                onChange={e => setSelectedRun(e.target.value)}
                className="bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded px-3 py-1.5"
              >
                {runIds.map(id => (
                  <option key={id} value={id}>{id}</option>
                ))}
              </select>
            )}
            <Link href="/" className="text-sm text-blue-400 hover:text-blue-300 underline">
              Dashboard →
            </Link>
          </div>
        </div>

        {runIds.length === 0 ? (
          <div className="rounded-xl bg-gray-900 border border-gray-800 p-8 text-center text-gray-400">
            <p className="text-lg font-medium mb-2">No backtest data yet</p>
            <p className="text-sm">Run the backtest script to populate this page:</p>
            <code className="block mt-3 bg-gray-800 rounded px-4 py-2 text-xs text-gray-300">
              python scripts/backtest.py --start 2026-04-21 --end 2026-04-27 --run-id apr21-27
            </code>
          </div>
        ) : (
          <>
            {/* Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="Signals Evaluated" value={String(runTrades.length)} />
              <StatCard label="Bets Simulated" value={String(betTrades.length)} />
              <StatCard label="Win Rate" value={winRate} />
              <StatCard
                label="Simulated P&L"
                value={betTrades.length > 0 ? `${totalPnl >= 0 ? '+' : ''}$${Math.abs(totalPnl).toFixed(2)}` : '—'}
                color={betTrades.length > 0 ? (totalPnl >= 0 ? 'text-green-400' : 'text-red-400') : 'text-gray-400'}
              />
            </div>

            {/* Filter toggle */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowBetsOnly(false)}
                className={`px-3 py-1 rounded text-sm ${!showBetsOnly ? 'bg-blue-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
              >
                All Signals
              </button>
              <button
                onClick={() => setShowBetsOnly(true)}
                className={`px-3 py-1 rounded text-sm ${showBetsOnly ? 'bg-blue-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
              >
                Bets Only
              </button>
              <span className="text-sm text-gray-500">({displayed.length} rows)</span>
            </div>

            {/* Results table */}
            <div className="rounded-xl bg-gray-900 border border-gray-800 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase tracking-wide">
                    <Th onClick={() => toggleSort('city')} label="City" icon={sortIcon('city')} />
                    <Th onClick={() => toggleSort('target_date')} label="Date" icon={sortIcon('target_date')} />
                    <th className="px-3 py-3 text-left font-medium">Contract</th>
                    <th className="px-3 py-3 text-right font-medium">Our %</th>
                    <th className="px-3 py-3 text-right font-medium">Mkt %</th>
                    <Th onClick={() => toggleSort('edge')} label="Edge" icon={sortIcon('edge')} right />
                    <th className="px-3 py-3 text-left font-medium">Action</th>
                    <th className="px-3 py-3 text-left font-medium">Result</th>
                    <Th onClick={() => toggleSort('pnl')} label="P&L" icon={sortIcon('pnl')} right />
                  </tr>
                </thead>
                <tbody>
                  {displayed.map(t => {
                    const p = parseTicker(t.ticker)
                    const edgeVal = parseFloat(t.edge)
                    return (
                      <tr key={t.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                        <td className="px-3 py-2.5 font-medium">{t.city ?? p.city}</td>
                        <td className="px-3 py-2.5 text-gray-300">{t.target_date ?? p.dateDisplay}</td>
                        <td className="px-3 py-2.5 text-gray-400 font-mono text-xs">{p.typeCode}</td>
                        <td className="px-3 py-2.5 text-right">{pct(t.our_probability)}</td>
                        <td className="px-3 py-2.5 text-right text-gray-400">{pct(t.market_probability)}</td>
                        <td className={`px-3 py-2.5 text-right font-medium ${edgeVal >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {edgeVal >= 0 ? '+' : ''}{(edgeVal * 100).toFixed(0)}%
                        </td>
                        <td className="px-3 py-2.5">
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${ACTION_STYLE[t.action] ?? 'bg-gray-800 text-gray-400'}`}>
                            {t.action}
                          </span>
                        </td>
                        <td className={`px-3 py-2.5 font-medium ${t.result ? RESULT_STYLE[t.result] ?? '' : 'text-gray-600'}`}>
                          {t.result ? t.result.toUpperCase() : '—'}
                        </td>
                        <td className={`px-3 py-2.5 text-right font-medium ${t.pnl ? (parseFloat(t.pnl) >= 0 ? 'text-green-400' : 'text-red-400') : 'text-gray-600'}`}>
                          {t.pnl ? dollars(t.pnl) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                  {displayed.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-3 py-8 text-center text-gray-500">
                        No records for this run.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <p className="text-xs text-gray-600">
              Market % is the last traded price before settlement — it approximates (but does not perfectly reflect)
              the pre-settlement market probability. P&L uses the same Kelly sizing logic as the live bot.
            </p>
          </>
        )}
      </div>
    </main>
  )
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-xl bg-gray-900 border border-gray-800 p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color ?? 'text-white'}`}>{value}</div>
    </div>
  )
}

function Th({ onClick, label, icon, right }: { onClick: () => void; label: string; icon: React.ReactNode; right?: boolean }) {
  return (
    <th
      className={`px-3 py-3 font-medium cursor-pointer select-none hover:text-gray-200 ${right ? 'text-right' : 'text-left'}`}
      onClick={onClick}
    >
      {label}{icon}
    </th>
  )
}
