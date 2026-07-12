import { useCallback, useEffect, useRef, useState } from 'react'
import { listContacts, getContact } from './api.js'
import { SourceBadge } from './ui.jsx'
import { humanizeTs } from './format.js'

function TimelineItem({ ix }) {
  const isIn = ix.direction === 'in'
  const intent = ix.extracted && (ix.extracted.intent || ix.extracted.Intent)
  return (
    <div className="timeline-item">
      <div className="timeline-top">
        <SourceBadge source={ix.source} />
        <span
          className={`dir-arrow ${isIn ? 'dir-in' : 'dir-out'}`}
          title={isIn ? 'inbound' : 'outbound'}
        >
          {isIn ? '←' : '→'}
        </span>
        <span className="timeline-ts">{humanizeTs(ix.ts)}</span>
      </div>
      <div className="timeline-body">{ix.body}</div>
      {intent ? <span className="intent-tag">intent: {String(intent)}</span> : null}
    </div>
  )
}

function ContactDrawer({ contactId, onClose }) {
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setDetail(null)
    setError('')
    getContact(contactId)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [contactId])

  const interactions = detail?.interactions || []

  return (
    <>
      <div className="drawer-veil" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-head">
          <button className="drawer-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
          <h2 className="drawer-name">{detail ? detail.name : 'Loading…'}</h2>
          <div className="drawer-meta">
            {detail
              ? [detail.company, detail.phone, detail.email].filter(Boolean).join(' · ') || '—'
              : ''}
          </div>
          {detail && (detail.tags || []).length > 0 && (
            <div style={{ marginTop: 8 }}>
              {detail.tags.map((t) => (
                <span key={t} className="tag-chip">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="drawer-body">
          {error && <div className="error-note">{error}</div>}
          {detail && interactions.length === 0 && (
            <div className="empty-state">No interactions yet.</div>
          )}
          {interactions.map((ix) => (
            <TimelineItem key={ix.id ?? `${ix.source}-${ix.external_id}`} ix={ix} />
          ))}
        </div>
      </aside>
    </>
  )
}

export default function ContactsPage() {
  const [contacts, setContacts] = useState([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [openId, setOpenId] = useState(null)
  const searchRef = useRef(search)
  searchRef.current = search

  const refresh = useCallback(async () => {
    try {
      const data = await listContacts(searchRef.current)
      setContacts(Array.isArray(data) ? data : data.results || [])
      setError('')
    } catch (e) {
      setError(`Could not load contacts: ${e.message}`)
    }
  }, [])

  // Initial + live polling every 5s so ingested data shows up.
  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [refresh])

  // Re-query when search changes (small debounce).
  useEffect(() => {
    const t = setTimeout(refresh, 250)
    return () => clearTimeout(t)
  }, [search, refresh])

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Contacts</h1>
          <span className="page-sub">Live — refreshes every 5s</span>
        </div>
        <input
          className="search-box"
          placeholder="Search name, company, phone, email…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {error && <div className="error-note">{error}</div>}

      {contacts.length === 0 && !error ? (
        <div className="empty-state">
          No contacts yet. Ask the agent to import your WhatsApp or Gmail conversations.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="contacts">
            <thead>
              <tr>
                <th>Name</th>
                <th>Company</th>
                <th>Phone</th>
                <th>Email</th>
                <th>Tags</th>
                <th>Interactions</th>
                <th>Last activity</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c) => (
                <tr key={c.id} onClick={() => setOpenId(c.id)}>
                  <td className="contact-name">{c.name}</td>
                  <td>{c.company || <span className="muted">—</span>}</td>
                  <td className="mono">{c.phone || <span className="muted">—</span>}</td>
                  <td className="mono">{c.email || <span className="muted">—</span>}</td>
                  <td>
                    {(c.tags || []).map((t) => (
                      <span key={t} className="tag-chip">
                        {t}
                      </span>
                    ))}
                  </td>
                  <td>
                    <span className="count-bub">{c.interaction_count ?? 0}</span>
                  </td>
                  <td className="muted">{humanizeTs(c.last_ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openId != null && <ContactDrawer contactId={openId} onClose={() => setOpenId(null)} />}
    </div>
  )
}
