import { sql } from '../lib/db'
import { Trade, Signal } from '../lib/utils'
import Dashboard from './components/Dashboard'

export const revalidate = 300

export default async function Page() {
  const [settled, active, signals] = await Promise.all([
    sql<Trade>(`
      SELECT id, ticker, side, contract_count, price_paid,
             our_probability, market_probability, result, pnl,
             created_at::text AS created_at
      FROM trades
      WHERE paper_trade = TRUE AND settled = TRUE
      ORDER BY created_at DESC
    `),
    sql<Trade>(`
      SELECT id, ticker, side, contract_count, price_paid,
             our_probability, market_probability, result, pnl,
             created_at::text AS created_at
      FROM trades
      WHERE paper_trade = TRUE AND settled = FALSE
      ORDER BY created_at DESC
      LIMIT 200
    `),
    sql<Signal>(`
      SELECT city, ticker, our_probability, market_probability, edge, action,
             created_at::text AS created_at
      FROM signals
      ORDER BY created_at DESC
      LIMIT 200
    `),
  ])

  return <Dashboard settled={settled} active={active} signals={signals} />
}
