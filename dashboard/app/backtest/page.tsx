import { sql } from '../../lib/db'
import { BacktestTrade } from '../../lib/utils'
import BacktestDashboard from './components/BacktestDashboard'

export const dynamic = 'force-dynamic'

export default async function BacktestPage() {
  const [trades, runRows] = await Promise.all([
    sql<BacktestTrade>(`
      SELECT id, run_id, ticker, city, target_date::text AS target_date,
             side, our_probability, market_probability, edge, action,
             contract_count, price_paid, result, pnl,
             created_at::text AS created_at
      FROM backtest_trades
      ORDER BY target_date DESC, ticker ASC
    `),
    sql<{ run_id: string }>(`
      SELECT DISTINCT run_id FROM backtest_trades ORDER BY run_id DESC
    `),
  ])

  return (
    <BacktestDashboard
      trades={trades}
      runIds={runRows.map(r => r.run_id)}
    />
  )
}
