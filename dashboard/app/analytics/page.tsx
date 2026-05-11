import { sql } from '../../lib/db'
import { Trade } from '../../lib/utils'
import AnalyticsDashboard from './components/AnalyticsDashboard'

export const dynamic = 'force-dynamic'

export default async function AnalyticsPage() {
  const trades = await sql<Trade>(`
    SELECT id, ticker, side, amount_usd, contract_count, price_paid,
           our_probability, market_probability, result, pnl,
           created_at::text AS created_at, gfs_run
    FROM trades
    WHERE paper_trade = TRUE AND settled = TRUE
    ORDER BY created_at ASC
  `)
  return <AnalyticsDashboard trades={trades} />
}
