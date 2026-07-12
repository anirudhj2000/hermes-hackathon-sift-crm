// Small shared UI components — Ink theme (sift-design-guidelines.md).

// Source badge: dot + word, mono 11px pill. ● WHATSAPP (--wa) / ● GMAIL (--gm).
export function SourceBadge({ source, onClick }) {
  const cls = `badge badge-${source || 'unknown'}`
  const label = (source || 'unknown').toUpperCase()
  const inner = (
    <>
      <span className="badge-dot" aria-hidden="true">
        ●
      </span>
      {label}
    </>
  )
  if (onClick) {
    return (
      <button type="button" className={`${cls} badge-btn`} onClick={onClick}>
        {inner}
      </button>
    )
  }
  return <span className={cls}>{inner}</span>
}

export function StatusPill({ status }) {
  return <span className={`pill pill-${status}`}>{status}</span>
}

// Blueprint metadata flourish (§3) — mono, prussian, one per card max.
export function Flourish({ children }) {
  if (!children) return null
  return <div className="flourish">{children}</div>
}
