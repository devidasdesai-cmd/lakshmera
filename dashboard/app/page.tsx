import { sql } from '../lib/db'
import { Trade, Signal } from '../lib/utils'
import Dashboard from './components/Dashboard'

export const dynamic = 'force-dynamic'

export default async function Page() {
  const [settled, active, signals, healthRow] = await Promise.all([
    sql<Trade>(`
      SELECT id, ticker, side, amount_usd, contract_count, price_paid,
             our_probability, market_probability, result, pnl,
             created_at::text AS created_at, gfs_run, strategy_version
      FROM trades
      WHERE paper_trade = TRUE AND settled = TRUE
      ORDER BY created_at DESC
    `),
    sql<Trade>(`
      SELECT id, ticker, side, amount_usd, contract_count, price_paid,
             our_probability, market_probability, result, pnl,
             created_at::text AS created_at, gfs_run, strategy_version
      FROM trades
      WHERE paper_trade = TRUE AND settled = FALSE
      ORDER BY created_at DESC
      LIMIT 200
    `),
    sql<Signal>(`
      SELECT city, ticker, our_probability, market_probability, edge, action, reason,
             created_at::text AS created_at
      FROM signals
      WHERE created_at >= NOW() - INTERVAL '3 days'
      ORDER BY created_at DESC
      LIMIT 1000
    `),
    sql<{ last_signal_at: string | null; signals_today: string; runs_today: string }>(`
      SELECT
        MAX(created_at)::text AS last_signal_at,
        COUNT(*) FILTER (WHERE created_at >= (NOW() AT TIME ZONE 'UTC')::date)::text AS signals_today,
        COUNT(DISTINCT date_trunc('hour', created_at))
          FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours')::text AS runs_today
      FROM signals
    `),
  ])

  const health = healthRow[0] ?? { last_signal_at: null, signals_today: '0', runs_today: '0' }

  return <Dashboard settled={settled} active={active} signals={signals} health={health} />
}
