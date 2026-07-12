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
