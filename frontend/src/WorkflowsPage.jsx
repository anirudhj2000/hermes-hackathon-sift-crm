import { useEffect, useRef, useState } from 'react'
import { listWorkflows, listRuns, listTables, runWorkflow, updateWorkflow, getRun } from './api.js'
import { StatusPill, Flourish } from './ui.jsx'
import { stepChain, runFlourish } from './format.js'
import WorkflowFlow from './WorkflowFlow.jsx'

const STAT_LABELS = [
  ['fetched', 'fetched'],
  ['kept', 'kept'],
  ['rows_created', 'rows +'],
  ['rows_updated', 'rows ~'],
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
        <span className="mono muted" style={{ fontSize: 11 }}>
          run {String(run.id).padStart(4, '0')}
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

function TriggerEditor({ current, onSave, onCancel, saving, error }) {
  const isInterval = current && typeof current === 'object'
  const [mode, setMode] = useState(isInterval ? 'interval' : 'manual')
  const [minutes, setMinutes] = useState(isInterval ? current.minutes : 30)
  const invalid = mode === 'interval' && (!minutes || Number(minutes) < 1)

  return (
    <div className="trigger-editor">
      <div className="trigger-editor-row">
        <span className="eyebrow">trigger</span>
        <label className={`trig-opt${mode === 'manual' ? ' active' : ''}`}>
          <input
            type="radio"
            name="trigger-mode"
            checked={mode === 'manual'}
            onChange={() => setMode('manual')}
          />
          MANUAL
        </label>
        <label className={`trig-opt${mode === 'interval' ? ' active' : ''}`}>
          <input
            type="radio"
            name="trigger-mode"
            checked={mode === 'interval'}
            onChange={() => setMode('interval')}
          />
          EVERY
          <input
            type="number"
            min="1"
            className="trig-min"
            value={minutes}
            disabled={mode !== 'interval'}
            onChange={(e) => setMinutes(e.target.value)}
            onFocus={() => setMode('interval')}
          />
          MIN
        </label>
        <button
          className="btn btn-primary"
          disabled={saving || invalid}
          onClick={() =>
            onSave(
              mode === 'interval' ? { type: 'interval', minutes: Number(minutes) } : 'manual',
            )
          }
        >
          {saving ? 'SAVING' : 'SAVE'}
        </button>
        <button className="btn" onClick={onCancel} disabled={saving}>
          CANCEL
        </button>
      </div>
      {mode === 'interval' && !invalid && (
        <div className="trig-hint">
          scheduler ticks every 30s — the workflow re-runs when {minutes}m have passed since
          the last run
        </div>
      )}
      {error && <div className="error-note" style={{ marginTop: 8 }}>{error}</div>}
    </div>
  )
}

function WorkflowCard({ wf, table, lastRun, onOpenTable, onPatched }) {
  const [run, setRun] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [showFlow, setShowFlow] = useState(true)
  const [expanded, setExpanded] = useState(false)
  const [editTrigger, setEditTrigger] = useState(false)
  const [trigSaving, setTrigSaving] = useState(false)
  const [trigError, setTrigError] = useState('')
  const pollRef = useRef(null)

  useEffect(() => () => clearInterval(pollRef.current), [])

  useEffect(() => {
    if (!expanded) return
    const onKey = (e) => e.key === 'Escape' && setExpanded(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  const saveTrigger = async (trigger) => {
    setTrigSaving(true)
    setTrigError('')
    try {
      const updated = await updateWorkflow(wf.id, { dsl: { ...wf.dsl, trigger } })
      if (onPatched && updated) onPatched(updated)
      setEditTrigger(false)
    } catch (e) {
      setTrigError(
        e.message.startsWith('405')
          ? 'the api cannot edit workflows yet (backend: add UpdateModelMixin to WorkflowViewSet) — meanwhile, ask the agent in chat to recreate this workflow with the new trigger'
          : `save failed — ${e.message}`,
      )
    } finally {
      setTrigSaving(false)
    }
  }

  const openTriggerEditor = () => {
    setTrigError('')
    setEditTrigger(true)
  }

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
      setError(`run failed — ${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const shown = run || lastRun
  const running = run && (run.status === 'pending' || run.status === 'running')
  const tableSlug = wf.dsl && wf.dsl.table
  const steps = stepChain(wf.dsl)

  return (
    <div className="card">
      <div className="wf-card-head">
        <h2 className="card-title">{wf.name}</h2>
        {shown && <StatusPill status={shown.status} />}
        <button className="btn btn-primary btn-arrow" onClick={onRun} disabled={busy || running}>
          {running ? 'RUNNING' : 'RUN'} <span className="arrow">→</span>
        </button>
      </div>

      <div className="wf-meta-row">
        {tableSlug ? (
          <button className="table-chip" onClick={() => onOpenTable && onOpenTable(tableSlug)}>
            TABLE {tableSlug}
          </button>
        ) : (
          <span className="table-chip table-chip-none">NO TABLE</span>
        )}
        {steps.length > 0 && (
          <span className="step-chain">
            {steps.map((s, i) => (
              <span key={`${s}-${i}`}>
                {i > 0 && <span className="step-arrow"> → </span>}
                {s}
              </span>
            ))}
          </span>
        )}
        <span className="flow-actions">
          <button className="flow-toggle" onClick={() => setExpanded(true)}>
            EXPAND ⤢
          </button>
          <button className="flow-toggle" onClick={() => setShowFlow((v) => !v)}>
            {showFlow ? 'HIDE FLOW' : 'FLOW ↳'}
          </button>
        </span>
      </div>

      {showFlow && wf.dsl && (
        <WorkflowFlow
          dsl={wf.dsl}
          table={table}
          onOpenTable={onOpenTable}
          onEditTrigger={openTriggerEditor}
        />
      )}

      {editTrigger && !expanded && (
        <TriggerEditor
          current={wf.dsl && wf.dsl.trigger}
          onSave={saveTrigger}
          onCancel={() => setEditTrigger(false)}
          saving={trigSaving}
          error={trigError}
        />
      )}

      {expanded && (
        <div className="wf-modal-scrim" onClick={() => setExpanded(false)}>
          <div className="wf-modal" onClick={(e) => e.stopPropagation()}>
            <div className="wf-modal-head">
              <span className="eyebrow">{wf.name}</span>
              <button className="flow-toggle" onClick={() => setExpanded(false)}>
                CLOSE ✕
              </button>
            </div>
            <WorkflowFlow
              dsl={wf.dsl}
              table={table}
              onOpenTable={onOpenTable}
              onEditTrigger={openTriggerEditor}
              interactive
              large
            />
            {editTrigger && (
              <TriggerEditor
                current={wf.dsl && wf.dsl.trigger}
                onSave={saveTrigger}
                onCancel={() => setEditTrigger(false)}
                saving={trigSaving}
                error={trigError}
              />
            )}
          </div>
        </div>
      )}

      <Flourish>{shown ? runFlourish(shown) : `DSL v2 · ${steps.length} STEPS`}</Flourish>

      {error && (
        <div className="error-note" style={{ marginTop: 10, marginBottom: 0 }}>
          {error}
        </div>
      )}
      {run && <RunStatus run={run} />}
    </div>
  )
}

export default function WorkflowsPage({ onOpenTable }) {
  const [workflows, setWorkflows] = useState(null) // null = loading
  const [lastRuns, setLastRuns] = useState({}) // workflow id → latest run
  const [tablesBySlug, setTablesBySlug] = useState({})
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
        if (alive) {
          setError(`could not reach the api — ${e.message}`)
          setWorkflows((prev) => prev || [])
        }
      }
      try {
        const runs = await listRuns()
        if (alive) {
          const map = {}
          for (const r of Array.isArray(runs) ? runs : runs.results || []) {
            const wfId = typeof r.workflow === 'object' ? r.workflow?.id : r.workflow
            if (wfId != null && (!map[wfId] || r.id > map[wfId].id)) map[wfId] = r
          }
          setLastRuns(map)
        }
      } catch {
        /* run metadata is ornament only */
      }
      try {
        const tbls = await listTables()
        if (alive) {
          const map = {}
          for (const t of Array.isArray(tbls) ? tbls : tbls.results || []) map[t.slug] = t
          setTablesBySlug(map)
        }
      } catch {
        /* flow diagram degrades to schema-less nodes */
      }
    }
    load()
    const t = setInterval(load, 5000) // pick up agent-created workflows live
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const patchWorkflow = (updated) =>
    setWorkflows((prev) => (prev || []).map((w) => (w.id === updated.id ? updated : w)))

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">PIPELINES</div>
          <h1 className="page-title">Workflows</h1>
        </div>
      </div>
      {error && <div className="error-note">{error}</div>}
      {workflows && workflows.length === 0 && !error ? (
        <div className="empty-state">NO WORKFLOWS YET — ASK THE AGENT TO BUILD A PIPELINE.</div>
      ) : (
        <div className="wf-grid">
          {(workflows || []).map((wf) => (
            <WorkflowCard
              key={wf.id}
              wf={wf}
              table={wf.dsl && wf.dsl.table ? tablesBySlug[wf.dsl.table] : undefined}
              lastRun={lastRuns[wf.id]}
              onOpenTable={onOpenTable}
              onPatched={patchWorkflow}
            />
          ))}
        </div>
      )}
    </div>
  )
}
