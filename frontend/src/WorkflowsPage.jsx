import { useEffect, useRef, useState } from 'react'
import { listWorkflows, runWorkflow, getRun } from './api.js'
import { StatusPill } from './ui.jsx'
import { prettyDsl } from './format.js'

const STAT_LABELS = [
  ['fetched', 'fetched'],
  ['kept', 'kept'],
  ['contacts_created', 'contacts +'],
  ['contacts_updated', 'contacts ~'],
  ['interactions_created', 'interactions +'],
]

function RunStatus({ run }) {
  const logRef = useRef(null)
  const log = run.log || ''
  const tail = log.split('\n').slice(-40).join('\n')

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [log])

  return (
    <div className="run-box">
      <div className="run-row">
        <StatusPill status={run.status} />
        <span className="mono muted" style={{ fontSize: 11.5 }}>
          run #{run.id}
        </span>
        <div className="stat-counters">
          {STAT_LABELS.map(([key, label]) =>
            run.stats && run.stats[key] != null ? (
              <span key={key} className="stat">
                {label} <b>{run.stats[key]}</b>
              </span>
            ) : null,
          )}
        </div>
      </div>
      {tail && (
        <div className="log-scroller" ref={logRef}>
          {tail}
        </div>
      )}
    </div>
  )
}

function WorkflowCard({ wf }) {
  const [run, setRun] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const pollRef = useRef(null)

  useEffect(() => () => clearInterval(pollRef.current), [])

  const pollRun = (runId) => {
    clearInterval(pollRef.current)
    const tick = async () => {
      try {
        const r = await getRun(runId)
        setRun(r)
        if (r.status === 'done' || r.status === 'error') clearInterval(pollRef.current)
      } catch (e) {
        setError(e.message)
        clearInterval(pollRef.current)
      }
    }
    tick()
    pollRef.current = setInterval(tick, 2000)
  }

  const onRun = async () => {
    setBusy(true)
    setError('')
    try {
      const { run_id } = await runWorkflow(wf.id)
      setRun({ id: run_id, status: 'pending', stats: {}, log: '' })
      pollRun(run_id)
    } catch (e) {
      setError(`Run failed: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const running = run && (run.status === 'pending' || run.status === 'running')

  return (
    <div className="card">
      <div className="wf-card-head">
        <h2 className="wf-name">{wf.name}</h2>
        <button className="btn btn-primary" onClick={onRun} disabled={busy || running}>
          {running ? 'Running…' : '▶ Run'}
        </button>
      </div>
      <pre className="dsl-block">{prettyDsl(wf.dsl)}</pre>
      {error && (
        <div className="error-note" style={{ marginTop: 10, marginBottom: 0 }}>
          {error}
        </div>
      )}
      {run && <RunStatus run={run} />}
    </div>
  )
}

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const data = await listWorkflows()
        if (alive) {
          setWorkflows(Array.isArray(data) ? data : data.results || [])
          setError('')
        }
      } catch (e) {
        if (alive) setError(`Could not load workflows: ${e.message}`)
      }
    }
    load()
    const t = setInterval(load, 5000) // pick up agent-created workflows live
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Workflows</h1>
          <span className="page-sub">Pipelines the agent (or you) can run against your sources</span>
        </div>
      </div>
      {error && <div className="error-note">{error}</div>}
      {workflows.length === 0 && !error ? (
        <div className="empty-state">
          No workflows yet. Ask the agent: “Import my WhatsApp chats from the last week”.
        </div>
      ) : (
        <div className="wf-grid">
          {workflows.map((wf) => (
            <WorkflowCard key={wf.id} wf={wf} />
          ))}
        </div>
      )}
    </div>
  )
}
