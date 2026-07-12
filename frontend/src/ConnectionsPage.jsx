import { useEffect, useState } from 'react'
import {
  listConnections,
  pairWhatsapp,
  connectGmail,
  disconnectSource,
  listWhatsappChats,
  scopeWhatsappChat,
} from './api.js'
import { StatusPill, Flourish } from './ui.jsx'
import { humanizeTs } from './format.js'

// Static MCP surface — tool names pinned by CONTRACTS.md agent tools.
const MCP_TOOLS = ['create_table', 'list_tables', 'query_records', 'create_workflow', 'run_workflow']

function qrToSrc(qr) {
  if (!qr) return null
  if (qr.startsWith('data:')) return qr
  // Assume base64 PNG payload if not already a data URI.
  return `data:image/png;base64,${qr}`
}

// "918125310746@s.whatsapp.net" → "+91 81253 10746"-ish display fallback.
function displayName(chat) {
  if (chat.name) return chat.name
  const digits = (chat.jid || '').split('@')[0].replace(/[^0-9]/g, '')
  return digits ? `+${digits}` : chat.jid
}

const HIDDEN_KEY = 'sift-hidden-chats'

function loadHidden() {
  try {
    return new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]'))
  } catch {
    return new Set()
  }
}

function ScopedChats() {
  const [chats, setChats] = useState(null) // null = loading
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [hidden, setHidden] = useState(loadHidden)

  const refresh = async () => {
    try {
      const data = await listWhatsappChats()
      const list = Array.isArray(data) ? data : data.results || []
      // Chats appear only once their first message has arrived.
      setChats(list.filter((c) => (c.message_count ?? 0) > 0))
      setError('')
    } catch (e) {
      setError(`could not load chats — ${e.message}`)
      setChats((prev) => prev || [])
    }
  }

  const onRemove = async (chat) => {
    if (chat.scoped) {
      // Hidden must also mean out of scope — never leave an invisible chat
      // fetchable by pipelines.
      try {
        await scopeWhatsappChat(chat.id, false)
      } catch {
        /* best-effort */
      }
    }
    setHidden((prev) => {
      const next = new Set(prev)
      next.add(chat.jid)
      localStorage.setItem(HIDDEN_KEY, JSON.stringify([...next]))
      return next
    })
  }

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 8000)
    return () => clearInterval(t)
  }, [])

  const onToggle = async (chat) => {
    setBusyId(chat.id)
    try {
      await scopeWhatsappChat(chat.id, !chat.scoped)
      setChats((prev) =>
        (prev || []).map((c) => (c.id === chat.id ? { ...c, scoped: !chat.scoped } : c)),
      )
    } catch (e) {
      setError(`scope change failed — ${e.message}`)
    } finally {
      setBusyId(null)
    }
  }

  const visible = (chats || []).filter((c) => !hidden.has(c.jid))
  const scopedCount = visible.filter((c) => c.scoped).length

  return (
    <div className="card conn-card-wide">
      <div className="conn-head">
        <div>
          <div className="conn-title">Scoped chats</div>
          <div className="conn-sub">only scoped chats are fetchable by pipelines</div>
        </div>
      </div>
      {error && <div className="error-note">{error}</div>}
      {chats && visible.length === 0 && !error ? (
        <div className="empty-state empty-inline">
          NO ACTIVE CHATS YET — A CHAT APPEARS HERE WHEN IT GETS A NEW MESSAGE AFTER PAIRING.
        </div>
      ) : (
        <div className="chat-list">
          {visible.map((c) => (
            <div key={c.id} className="chat-row">
              <div className="chat-row-main">
                <span className="chat-name">
                  {displayName(c)}
                  {c.is_group && <span className="group-tag">GROUP</span>}
                </span>
                <span className="chat-jid">{c.jid}</span>
              </div>
              <span className="chat-ts">{humanizeTs(c.last_message_at)}</span>
              <button
                className={`scope-toggle ${c.scoped ? 'on' : ''}`}
                disabled={busyId === c.id}
                onClick={() => onToggle(c)}
                aria-pressed={!!c.scoped}
              >
                {c.scoped ? 'SCOPED' : 'IGNORED'}
              </button>
              <button
                className="chat-remove"
                title="remove from list (unscopes the chat)"
                aria-label={`remove ${displayName(c)} from list`}
                onClick={() => onRemove(c)}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
      {chats && visible.length > 0 && (
        <Flourish>{`${scopedCount}/${visible.length} CHATS IN SCOPE`}</Flourish>
      )}
    </div>
  )
}

export default function ConnectionsPage() {
  const [connections, setConnections] = useState([])
  const [error, setError] = useState('')
  const [qr, setQr] = useState(null)
  const [phone, setPhone] = useState('')
  const [pairCode, setPairCode] = useState(null)
  const [waBusy, setWaBusy] = useState(false)
  const [gmBusy, setGmBusy] = useState(false)
  const [gmNote, setGmNote] = useState('')

  const refresh = async () => {
    try {
      const data = await listConnections()
      setConnections(Array.isArray(data) ? data : data.results || [])
      setError('')
    } catch (e) {
      setError(`could not reach the api — ${e.message}`)
    }
  }

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [])

  const statusOf = (source) =>
    connections.find((c) => c.source === source)?.status || 'disconnected'

  const onPair = async () => {
    setWaBusy(true)
    setError('')
    try {
      const res = await pairWhatsapp()
      if (res.connected) {
        setQr(null)
        setPairCode(null)
      } else if (res.qr) {
        setQr(res.qr)
        setPairCode(null)
      }
      refresh()
    } catch (e) {
      setError(`pairing failed — ${e.message}`)
    } finally {
      setWaBusy(false)
    }
  }

  const onPairCode = async () => {
    const digits = phone.replace(/[^0-9]/g, '')
    if (!digits) {
      setError('enter your number with country code, e.g. 91 98765 43210')
      return
    }
    setWaBusy(true)
    setError('')
    try {
      const res = await pairWhatsapp(digits)
      if (res.connected) {
        setPairCode(null)
        setQr(null)
      } else if (res.code) {
        setPairCode(res.code)
        setQr(null)
      } else {
        setError('no code returned — is the sidecar running?')
      }
      refresh()
    } catch (e) {
      setError(`pairing code failed — ${e.message}`)
    } finally {
      setWaBusy(false)
    }
  }

  const formatCode = (code) =>
    code && code.length === 8 ? `${code.slice(0, 4)}-${code.slice(4)}` : code

  const onGmail = async () => {
    setGmBusy(true)
    setError('')
    setGmNote('')
    try {
      const res = await connectGmail()
      if (res.redirect_url) {
        setGmNote(`continue in google: ${res.redirect_url}`)
        window.open(res.redirect_url, '_blank', 'noopener')
      } else {
        setGmNote(`status: ${res.status}`)
      }
      refresh()
    } catch (e) {
      setError(`gmail connect failed — ${e.message}`)
    } finally {
      setGmBusy(false)
    }
  }

  const onDisconnect = async (source) => {
    const setBusy = source === 'whatsapp' ? setWaBusy : setGmBusy
    setBusy(true)
    setError('')
    try {
      await disconnectSource(source)
      if (source === 'whatsapp') {
        setQr(null)
        setPairCode(null)
      } else {
        setGmNote('')
      }
      refresh()
    } catch (e) {
      setError(`disconnect failed — ${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const waStatus = statusOf('whatsapp')
  const gmStatus = statusOf('gmail')

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">SOURCES</div>
          <h1 className="page-title">Connections</h1>
        </div>
      </div>
      {error && <div className="error-note">{error}</div>}

      <div className="conn-grid">
        <div className="card">
          <div className="conn-head">
            <span className="src-dot wa" aria-hidden="true" />
            <div>
              <div className="conn-title">WhatsApp</div>
              <div className="conn-sub">via baileys sidecar</div>
            </div>
            <StatusPill status={waStatus} />
          </div>
          {waStatus === 'connected' ? (
            <>
              <p className="conn-note">linked and listening for messages.</p>
              <button
                className="btn btn-secondary btn-arrow"
                onClick={() => onDisconnect('whatsapp')}
                disabled={waBusy}
              >
                {waBusy ? 'DISCONNECTING' : 'DISCONNECT'} <span className="arrow">→</span>
              </button>
            </>
          ) : (
            <>
              <div className="pair-row">
                <input
                  className="input pair-phone"
                  type="tel"
                  placeholder="phone with country code · 91 98765 43210"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  aria-label="Phone number with country code"
                />
                <button
                  className="btn btn-primary btn-arrow"
                  onClick={onPairCode}
                  disabled={waBusy}
                >
                  {waBusy ? 'REQUESTING' : 'GET PAIRING CODE'} <span className="arrow">→</span>
                </button>
              </div>
              <button className="btn btn-secondary btn-arrow" onClick={onPair} disabled={waBusy}>
                {qr ? 'REFRESH QR' : 'PAIR WITH QR INSTEAD'} <span className="arrow">→</span>
              </button>
            </>
          )}
          {pairCode && waStatus !== 'connected' && (
            <div className="pair-code-wrap">
              <div className="pair-code">{formatCode(pairCode)}</div>
              <div className="qr-hint">
                whatsapp → settings → linked devices → link a device → link with phone number
                instead
              </div>
            </div>
          )}
          {qr && waStatus !== 'connected' && (
            <div className="qr-wrap">
              <img src={qrToSrc(qr)} alt="WhatsApp pairing QR code" />
              <div className="qr-hint">whatsapp → settings → linked devices → link a device</div>
            </div>
          )}
        </div>

        <div className="card">
          <div className="conn-head">
            <span className="src-dot gm" aria-hidden="true" />
            <div>
              <div className="conn-title">Gmail</div>
              <div className="conn-sub">via composio</div>
            </div>
            <StatusPill status={gmStatus} />
          </div>
          {gmStatus === 'connected' ? (
            <>
              <p className="conn-note">mailbox connected and readable.</p>
              <button
                className="btn btn-secondary btn-arrow"
                onClick={() => onDisconnect('gmail')}
                disabled={gmBusy}
              >
                {gmBusy ? 'DISCONNECTING' : 'DISCONNECT'} <span className="arrow">→</span>
              </button>
            </>
          ) : (
            <button className="btn btn-primary btn-arrow" onClick={onGmail} disabled={gmBusy}>
              {gmBusy ? 'CONNECTING' : 'CONNECT GMAIL'} <span className="arrow">→</span>
            </button>
          )}
          {gmNote && <p className="conn-note mono breakall">{gmNote}</p>}
        </div>

        <ScopedChats />

        <div className="card conn-card-wide">
          <div className="conn-head">
            <span className="src-dot mcp" aria-hidden="true" />
            <div>
              <div className="conn-title">MCP server</div>
              <div className="conn-sub">expose sift tables to any mcp client</div>
            </div>
          </div>
          <p className="conn-note">
            point your client at <span className="mono">localhost:8080</span> — the server exposes
            the sift toolset:
          </p>
          <div className="chip-row">
            {MCP_TOOLS.map((t) => (
              <span key={t} className="col-chip">
                {t}
              </span>
            ))}
          </div>
          <Flourish>{`MCP · LOCALHOST:8080 · ${MCP_TOOLS.length} TOOLS`}</Flourish>
        </div>
      </div>
    </div>
  )
}
