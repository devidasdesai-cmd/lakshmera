// Server-only — never import this in client components.
import { Pool } from 'pg'

declare global {
  // eslint-disable-next-line no-var
  var _pgPool: Pool | undefined
}

function getPool(): Pool {
  if (!global._pgPool) {
    global._pgPool = new Pool({
      connectionString: process.env.SUPABASE_DB_URL,
      ssl: { rejectUnauthorized: false },
      max: 3,
    })
  }
  return global._pgPool
}

export async function sql<T>(text: string): Promise<T[]> {
  const client = await getPool().connect()
  try {
    const res = await client.query<T>(text)
    return res.rows
  } finally {
    client.release()
  }
}
