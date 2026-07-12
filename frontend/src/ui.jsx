// Small shared UI components.

export function SourceBadge({ source }) {
  const icon = source === 'whatsapp' ? '🟢' : source === 'gmail' ? '✉️' : '•'
  return (
    <span className={`badge badge-${source}`}>
      <span aria-hidden="true">{icon}</span>
      {source}
    </span>
  )
}

export function StatusPill({ status }) {
  return <span className={`pill pill-${status}`}>{status}</span>
}
