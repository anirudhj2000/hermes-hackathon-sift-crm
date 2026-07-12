import { useEffect, useState } from 'react'
import { listConnections, pairWhatsapp, connectGmail } from './api.js'
import { StatusPill } from './ui.jsx'

function qrToSrc(qr) {
  if (!qr) return null
  if (qr.startsWith('data:')) return qr
  // Assume base64 PNG payload if not already a data URI.
  return `data:image/png;base64,${qr}`
}

export default function ConnectionsPage() {
  const [connections, setConnections] = useState([])
  const [error, setError] = useState('')
  const [qr, setQr] = useState(null)
  const [waBusy, setWaBusy] = useState(false)
  const [gmBusy, setGmBusy] = useState(false)
  const [gmNote, setGmNote] = useState('')

  const refresh = async () => {
    try {
      const data = await listConnections()
      setConnections(Array.isArray(data) ? data : data.results || [])
      setError('')
    } catch (e) {
      setError(`Could not load connections: ${e.message}`)
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
      } else if (res.qr) {
        setQr(res.qr)
      }
      refresh()
    } catch (e) {
      setError(`Pairing failed: ${e.message}`)
    } finally {
      setWaBusy(false)
    }
  }

  const onGmail = async () => {
    setGmBusy(true)
    setError('')
    setGmNote('')
    try {
      const res = await connectGmail()
      if (res.redirect_url) {
        setGmNote(`Continue in Google: ${res.redirect_url}`)
        window.open(res.redirect_url, '_blank', 'noopener')
      } else {
        setGmNote(`Status: ${res.status}`)
      }
      refresh()
    } catch (e) {
      setError(`Gmail connect failed: ${e.message}`)
    } finally {
      setGmBusy(false)
    }
  }

  const waStatus = statusOf('whatsapp')
  const gmStatus = statusOf('gmail')

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Connections</h1>
          <span className="page-sub">Message sources the agent can pull from</span>
        </div>
      </div>
      {error && <div className="error-note">{error}</div>}

      <div className="conn-grid">
        <div className="card">
          <div className="conn-head">
            <div className="conn-logo whatsapp">💬</div>
            <div>
              <div className="conn-title">WhatsApp</div>
              <div className="conn-sub">via Baileys sidecar</div>
            </div>
            <StatusPill status={waStatus} />
          </div>
          {waStatus === 'connected' ? (
            <p className="muted" style={{ margin: '6px 0 0', fontSize: 13 }}>
              Linked and listening for messages.
            </p>
          ) : (
            <button className="btn btn-primary" onClick={onPair} disabled={waBusy}>
              {waBusy ? 'Requesting…' : qr ? 'Refresh QR' : 'Pair'}
            </button>
          )}
          {qr && waStatus !== 'connected' && (
            <div className="qr-wrap">
              <img src={qrToSrc(qr)} alt="WhatsApp pairing QR code" />
              <div className="qr-hint">
                WhatsApp → Settings → Linked devices → Link a device
              </div>
            </div>
          )}
        </div>

        <div className="card">
          <div className="conn-head">
            <div className="conn-logo gmail">📧</div>
            <div>
              <div className="conn-title">Gmail</div>
              <div className="conn-sub">via Composio</div>
            </div>
            <StatusPill status={gmStatus} />
          </div>
          {gmStatus === 'connected' ? (
            <p className="muted" style={{ margin: '6px 0 0', fontSize: 13 }}>
              Mailbox connected and readable.
            </p>
          ) : (
            <button className="btn btn-primary" onClick={onGmail} disabled={gmBusy}>
              {gmBusy ? 'Connecting…' : 'Connect'}
            </button>
          )}
          {gmNote && (
            <p className="muted mono" style={{ marginTop: 10, fontSize: 11.5, wordBreak: 'break-all' }}>
              {gmNote}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
