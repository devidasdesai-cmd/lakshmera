// Vercel Cron-triggered endpoint that fires the GitHub Actions bot workflow via
// workflow_dispatch. Vercel Cron is much more reliable than GitHub's own scheduler;
// after 5 days of confirmed-unreliable GitHub Actions scheduling for this account,
// we moved the scheduling layer here.
//
// Required environment variables (set in Vercel project settings):
//   GITHUB_TOKEN  — PAT with actions:write scope on the lakshmera repo
//   GITHUB_OWNER  — repo owner (e.g., "devidasdesai-cmd")
//   GITHUB_REPO   — repo name (e.g., "lakshmera")
//   CRON_SECRET   — random string; Vercel auto-passes this as Bearer auth on cron calls
//
// Schedule is defined in dashboard/vercel.json.

import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const WORKFLOW_FILE = 'bot.yml'
const REF = 'main'

async function triggerBot() {
  const owner = process.env.GITHUB_OWNER
  const repo = process.env.GITHUB_REPO
  const token = process.env.GITHUB_TOKEN

  if (!owner || !repo || !token) {
    return {
      ok: false,
      status: 500,
      error: 'Missing required env vars: GITHUB_OWNER, GITHUB_REPO, or GITHUB_TOKEN',
    }
  }

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${WORKFLOW_FILE}/dispatches`
  const githubResp = await fetch(url, {
    method: 'POST',
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ref: REF }),
  })

  if (!githubResp.ok) {
    const body = await githubResp.text()
    return {
      ok: false,
      status: githubResp.status,
      error: `GitHub API rejected: ${body.slice(0, 500)}`,
    }
  }

  return { ok: true, status: 204, triggered_at: new Date().toISOString() }
}

export async function GET(request: NextRequest) {
  // Vercel Cron sends GET with Authorization: Bearer <CRON_SECRET>
  // Manual debug calls (no secret) just return a help message.
  const auth = request.headers.get('authorization')
  const cronSecret = process.env.CRON_SECRET

  if (cronSecret && auth !== `Bearer ${cronSecret}`) {
    return new NextResponse('Unauthorized', { status: 401 })
  }

  const result = await triggerBot()
  return NextResponse.json(result, { status: result.ok ? 200 : (result.status || 500) })
}

export async function POST(request: NextRequest) {
  // Manual trigger path — same auth requirement
  const auth = request.headers.get('authorization')
  const cronSecret = process.env.CRON_SECRET

  if (cronSecret && auth !== `Bearer ${cronSecret}`) {
    return new NextResponse('Unauthorized', { status: 401 })
  }

  const result = await triggerBot()
  return NextResponse.json(result, { status: result.ok ? 200 : (result.status || 500) })
}
