import { sql } from '../lib/db'

// Revalidate every 5 minutes (bot runs every 6 hours, this is plenty)
export const revalidate = 300

// ─── Types ───────────────────────────────────────────────────────────────────

interface Stats {
  settled: string
  open_positions: string
  total_pnl: string
  wins: string
  losses: string
}

interface Trade {
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

interface Signal {
  city: string
  ticker: string
  our_probability: string
  market_probability: string
  edge: string
  action: string
  created_at: string
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SERIES_TO_CITY: Record<string, string> = {
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

function parseTicker(ticker: string) {
  const [series = '', dateStr = '', typeCode = ''] = ticker.split('-')
  const city = SERIES_TO_CITY[series] ?? series

  let dateDisplay = dateStr
  const m = dateStr.match(/^(\d{2})([A-Z]{3})(\d{2})$/)
  if (m) {
    const d = new Date(2000 + parseInt(m[1]), MONTHS[m[2]] ?? 0, parseInt(m[3]))
    dateDisplay = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  return { city, dateDisplay, typeCode }
}

function pct(val: string | number | null): string {
  if (val === null || val === undefined) return '—'
  return `${(parseFloat(String(val)) * 100).toFixed(0)}%`
}

function dollars(val: string | number | null, showSign = true): string {
  if (val === null || val === undefined) return '—'
  const n = parseFloat(String(val))
  const sign = showSign && n >= 0 ? '+' : ''
  return `${sign}$${Math.abs(n).toFixed(2)}`
}

function edgeColor(edge: number): string {
  return edge >= 0 ? 'text-emerald-400' : 'text-red-400'
}

function actionBadge(action: string) {
  const styles: Record<string, string> = {
    BET_YES:         'bg-emerald-950 text-emerald-400 border-emerald-800',
    BET_NO:          'bg-red-950 text-red-400 border-red-800',
    NO_BET:          'bg-gray-800 text-gray-500 border-gray-700',
    SUSPICIOUS_EDGE: 'bg-amber-950 text-amber-400 border-amber-800',
  }
  const cls = styles[action] ?? 'bg-gray-800 text-gray-400 border-gray-700'
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded border ${cls}`}>
      {action}
    </span>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function Dashboard() {
  const [statsRows, settled, active, signals] = await Promise.all([
    sql<Stats>(`
      SELECT
        COUNT(*) FILTER (WHERE settled = TRUE)::text          AS settled,
        COUNT(*) FILTER (WHERE settled = FALSE)::text         AS open_positions,
        COALESCE(ROUND(SUM(pnl) FILTER (WHERE settled = TRUE)::numeric, 2), 0)::text
                                                              AS total_pnl,
        COUNT(*) FILTER (WHERE settled = TRUE AND pnl > 0)::text  AS wins,
        COUNT(*) FILTER (WHERE settled = TRUE AND pnl <= 0)::text AS losses
      FROM trades
      WHERE paper_trade = TRUE
    `),
    sql<Trade>(`
      SELECT id, ticker, side, contract_count, price_paid,
             our_probability, market_probability, result, pnl, created_at
      FROM trades
      WHERE settled = TRUE AND paper_trade = TRUE
      ORDER BY created_at DESC
      LIMIT 30
    `),
    sql<Trade>(`
      SELECT id, ticker, side, contract_count, price_paid,
             our_probability, market_probability, result, pnl, created_at
      FROM trades
      WHERE settled = FALSE AND paper_trade = TRUE
      ORDER BY created_at DESC
      LIMIT 50
    `),
    sql<Signal>(`
      SELECT city, ticker, our_probability, market_probability, edge, action, created_at
      FROM signals
      ORDER BY created_at DESC
      LIMIT 50
    `),
  ])

  const stats     = statsRows[0] ?? { settled: '0', open_positions: '0', total_pnl: '0', wins: '0', losses: '0' }
  const totalPnl  = parseFloat(stats.total_pnl)
  const settled_n = parseInt(stats.settled)
  const wins_n    = parseInt(stats.wins)
  const winRate   = settled_n > 0 ? `${(wins_n / settled_n * 100).toFixed(1)}%` : '—'

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-6">

      {/* ── Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">LAKSHMERA</h1>
          <p className="text-sm text-gray-500 mt-0.5">Weather Prediction Market Bot</p>
        </div>
        <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-950 text-amber-400 border border-amber-800 mt-1">
          PAPER TRADING
        </span>
      </div>

      {/* ── Stats cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Total P&L"
          value={dollars(stats.total_pnl)}
          valueClass={totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}
          sub="paper trades only"
        />
        <StatCard
          label="Win Rate"
          value={winRate}
          valueClass="text-white"
          sub={`${stats.wins}W · ${stats.losses}L`}
        />
        <StatCard
          label="Open Positions"
          value={stats.open_positions}
          valueClass="text-sky-400"
          sub="pending settlement"
        />
        <StatCard
          label="Settled Trades"
          value={stats.settled}
          valueClass="text-white"
          sub="total resolved"
        />
      </div>

      {/* ── Recent results ── */}
      <Section title="Recent Results" badge={`${settled.length} shown`}>
        {settled.length === 0 ? (
          <Empty>No settled trades yet — check back after markets resolve (usually same evening).</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <Thead cols={['City', 'Date', 'Contract', 'Side', 'Price', 'Result', 'P&L']} />
              <tbody className="divide-y divide-gray-800/60">
                {settled.map(t => {
                  const { city, dateDisplay, typeCode } = parseTicker(t.ticker)
                  const won = t.result === t.side
                  const pnlVal = parseFloat(t.pnl ?? '0')
                  return (
                    <tr key={t.id} className="hover:bg-gray-800/40 transition-colors">
                      <Td>{city}</Td>
                      <Td muted>{dateDisplay}</Td>
                      <Td mono>{typeCode}</Td>
                      <Td>
                        <span className={t.side === 'yes' ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
                          {t.side.toUpperCase()}
                        </span>
                      </Td>
                      <Td mono>{t.price_paid ? parseFloat(t.price_paid).toFixed(2) : '—'}</Td>
                      <Td>
                        {t.result ? (
                          <span className={won ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
                            {won ? 'WON' : 'LOST'}
                          </span>
                        ) : '—'}
                      </Td>
                      <Td>
                        <span className={`font-medium tabular-nums ${pnlVal >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {dollars(t.pnl)}
                        </span>
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* ── Active positions ── */}
      <Section title="Active Positions" badge={`${active.length} open`}>
        {active.length === 0 ? (
          <Empty>No open positions.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <Thead cols={['City', 'Date', 'Contract', 'Side', 'Price', 'Our %', 'Mkt %']} />
              <tbody className="divide-y divide-gray-800/60">
                {active.map(t => {
                  const { city, dateDisplay, typeCode } = parseTicker(t.ticker)
                  return (
                    <tr key={t.id} className="hover:bg-gray-800/40 transition-colors">
                      <Td>{city}</Td>
                      <Td muted>{dateDisplay}</Td>
                      <Td mono>{typeCode}</Td>
                      <Td>
                        <span className={t.side === 'yes' ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
                          {t.side.toUpperCase()}
                        </span>
                      </Td>
                      <Td mono>{t.price_paid ? parseFloat(t.price_paid).toFixed(2) : '—'}</Td>
                      <Td mono>{pct(t.our_probability)}</Td>
                      <Td mono>{pct(t.market_probability)}</Td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* ── Signal log ── */}
      <Section title="Signal Log" badge="last 50">
        {signals.length === 0 ? (
          <Empty>No signals logged yet.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <Thead cols={['City', 'Date', 'Contract', 'Our %', 'Mkt %', 'Edge', 'Action']} />
              <tbody className="divide-y divide-gray-800/60">
                {signals.map((s, i) => {
                  const { dateDisplay, typeCode } = parseTicker(s.ticker)
                  const edge = parseFloat(s.edge)
                  return (
                    <tr key={i} className="hover:bg-gray-800/40 transition-colors">
                      <Td>{s.city}</Td>
                      <Td muted>{dateDisplay}</Td>
                      <Td mono>{typeCode}</Td>
                      <Td mono>{pct(s.our_probability)}</Td>
                      <Td mono>{pct(s.market_probability)}</Td>
                      <Td>
                        <span className={`tabular-nums font-medium ${edgeColor(edge)}`}>
                          {edge >= 0 ? '+' : ''}{edge.toFixed(2)}
                        </span>
                      </Td>
                      <Td>{actionBadge(s.action)}</Td>
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

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value, valueClass, sub }: {
  label: string
  value: string
  valueClass: string
  sub: string
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold tabular-nums mt-1 ${valueClass}`}>{value}</p>
      <p className="text-xs text-gray-600 mt-1">{sub}</p>
    </div>
  )
}

function Section({ title, badge, children }: {
  title: string
  badge?: string
  children: React.ReactNode
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{title}</h2>
        {badge && <span className="text-xs text-gray-600">{badge}</span>}
      </div>
      {children}
    </div>
  )
}

function Thead({ cols }: { cols: string[] }) {
  return (
    <thead>
      <tr className="border-b border-gray-800">
        {cols.map(c => (
          <th key={c} className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
            {c}
          </th>
        ))}
      </tr>
    </thead>
  )
}

function Td({ children, muted, mono }: {
  children: React.ReactNode
  muted?: boolean
  mono?: boolean
}) {
  return (
    <td className={`px-4 py-2.5 ${muted ? 'text-gray-500' : 'text-gray-300'} ${mono ? 'tabular-nums font-mono text-xs' : ''}`}>
      {children}
    </td>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 py-10 text-center text-sm text-gray-600">{children}</div>
  )
}
