import { NextRequest, NextResponse } from 'next/server'
import { createAdminClient } from '@/lib/supabase/admin'

// GitHub Actions control for the mobile app (run / cancel / enable / disable
// workflows, start Easy Apply).
//
// SECURITY: the GitHub token (GH_PAT) stays on the server. It used to be
// compiled into the APK, which is published on the public Releases page, so
// anyone could extract it. Now the app sends its Supabase session token and
// only the admin account (ADMIN_EMAIL, confirmed email) may use this route.

const OWNER = 'mohamedkhalaf0045-stack'
const REPO  = 'job-alert'

// Only these workflows can be controlled from the app.
const ALLOWED_WORKFLOWS = new Set([
  'job-alert.yml',
  'enricher.yml',
  'fastlane-cloud.yml',
  'gap-monitor.yml',
  'user-alerts.yml',
  'daily-digest.yml',
  'easy-apply.yml',
])

type Action = 'dispatch' | 'cancel' | 'enable' | 'disable'

async function gh(path: string, method: string, body?: unknown) {
  return fetch(`https://api.github.com/repos/${OWNER}/${REPO}${path}`, {
    method,
    headers: {
      Authorization:          `Bearer ${process.env.GH_PAT}`,
      Accept:                 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
}

/** Resolve a numeric workflow id (from the runs API) to its file name. */
async function workflowFile(workflow: string | number): Promise<string | null> {
  if (typeof workflow === 'string' && ALLOWED_WORKFLOWS.has(workflow)) return workflow
  if (typeof workflow === 'number' || /^\d+$/.test(String(workflow))) {
    const res = await gh(`/actions/workflows/${workflow}`, 'GET')
    if (!res.ok) return null
    const data = await res.json() as { path?: string }
    const file = (data.path ?? '').split('/').pop() ?? ''
    return ALLOWED_WORKFLOWS.has(file) ? file : null
  }
  return null
}

export async function POST(req: NextRequest) {
  const authHeader = req.headers.get('Authorization') ?? ''
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : ''
  if (!token) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const admin = createAdminClient()
  const { data: { user }, error } = await admin.auth.getUser(token)
  if (error || !user || !user.email_confirmed_at ||
      !process.env.ADMIN_EMAIL ||
      user.email?.toLowerCase() !== process.env.ADMIN_EMAIL.toLowerCase()) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }
  if (!process.env.GH_PAT) {
    return NextResponse.json({ error: 'GH_PAT not set on the server' }, { status: 500 })
  }

  let body: { action?: Action; workflow?: string | number; run_id?: number; job_id?: string; cv_only?: boolean }
  try { body = await req.json() } catch { return NextResponse.json({ error: 'Bad JSON' }, { status: 400 }) }

  const action = body.action
  if (action === 'cancel') {
    const runId = Number(body.run_id)
    if (!Number.isInteger(runId) || runId <= 0) {
      return NextResponse.json({ error: 'Bad run_id' }, { status: 400 })
    }
    const res = await gh(`/actions/runs/${runId}/cancel`, 'POST')
    return NextResponse.json({ ok: res.status === 202 }, { status: res.status === 202 ? 200 : 502 })
  }

  if (action !== 'dispatch' && action !== 'enable' && action !== 'disable') {
    return NextResponse.json({ error: 'Unknown action' }, { status: 400 })
  }
  const file = await workflowFile(body.workflow ?? '')
  if (!file) return NextResponse.json({ error: 'Workflow not allowed' }, { status: 400 })

  if (action === 'enable' || action === 'disable') {
    const res = await gh(`/actions/workflows/${file}/${action}`, 'PUT')
    return NextResponse.json({ ok: res.status === 204 }, { status: res.status === 204 ? 200 : 502 })
  }

  const inputs: Record<string, string | boolean> = {}
  if (file === 'easy-apply.yml') {
    const jobId = String(body.job_id ?? '')
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(jobId)) {
      return NextResponse.json({ error: 'Bad job_id' }, { status: 400 })
    }
    inputs.job_id = jobId
    if (body.cv_only) inputs.cv_only = true
  }
  const res = await gh(`/actions/workflows/${file}/dispatches`, 'POST', {
    ref: 'main',
    ...(Object.keys(inputs).length ? { inputs } : {}),
  })
  return NextResponse.json({ ok: res.status === 204 }, { status: res.status === 204 ? 200 : 502 })
}
