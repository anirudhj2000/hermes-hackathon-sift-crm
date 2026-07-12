// Non-component helpers (kept out of .jsx files for fast refresh).

export function humanizeTs(iso) {
  if (!iso) return '—'
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return '—'
  const secs = Math.floor((Date.now() - then.getTime()) / 1000)
  if (secs < 45) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function prettyDsl(dsl) {
  try {
    return JSON.stringify(dsl, null, 2)
  } catch {
    return String(dsl)
  }
}

// "fetch → filter → extract → upsert" from a v2 DSL.
export function stepChain(dsl) {
  const steps = dsl && Array.isArray(dsl.steps) ? dsl.steps : []
  return steps.map((s) => s && s.type).filter(Boolean)
}

// Zero-padded run number for blueprint metadata lines: 42 → "0042".
export function padRun(n) {
  return String(n ?? 0).padStart(4, '0')
}

// One-per-card blueprint metadata line from a v2 run's stats — only TRUE values.
export function runFlourish(run) {
  if (!run) return null
  const s = run.stats || {}
  const rows = (s.rows_created ?? 0) + (s.rows_updated ?? 0)
  if (s.fetched == null && !rows) return `RUN ${padRun(run.id)} · ${String(run.status || '').toUpperCase()}`
  return `RUN ${padRun(run.id)} · ${s.fetched ?? 0} MSGS → ${rows} ROWS`
}
