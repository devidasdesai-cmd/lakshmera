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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function sql<T = Record<string, any>>(text: string): Promise<T[]> {
  const client = await getPool().connect()
  try {
    const res = await client.query(text)
    return res.rows as T[]
  } finally {
    client.release()
  }
}
