import { useEffect, useState } from 'react'
import { listTables, listRuns } from './api.js'
import { Flourish } from './ui.jsx'
import { runFlourish } from './format.js'

// Latest run per table slug (runs matched via stats.table).
function latestRunBySlug(runs) {
  const map = {}
  for (const run of runs) {
    const slug = run.stats && run.stats.table
    if (!slug) continue
    if (!map[slug] || run.id > map[slug].id) map[slug] = run
  }
  return map
}

function TableCard({ table, lastRun, onOpen }) {
  const columns = table.columns || []
  return (
    <button className="card table-card" onClick={onOpen}>
      <div className="table-card-head">
        <h2 className="card-title">{table.name}</h2>
        <span className="record-count">
          {table.record_count ?? 0}
          <em>ROWS</em>
        </span>
      </div>
      <div className="chip-row">
        {columns.map((c) => (
          <span
            key={c.name}
            className={`col-chip ${(table.dedupe_keys || []).includes(c.name) ? 'col-chip-key' : ''}`}
            title={c.description || c.type}
          >
            {c.name}
          </span>
        ))}
      </div>
      <Flourish>
        {lastRun
          ? runFlourish(lastRun)
          : `SCHEMA · ${columns.length} COLS · NO RUNS YET`}
      </Flourish>
    </button>
  )
}

export default function TablesPage({ onOpenTable }) {
  const [tables, setTables] = useState(null) // null = loading
  const [runsBySlug, setRunsBySlug] = useState({})
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const data = await listTables()
        if (!alive) return
        setTables(Array.isArray(data) ? data : data.results || [])
        setError('')
      } catch (e) {
        if (alive) {
          setError(`could not reach the api — ${e.message}`)
          setTables((prev) => prev || [])
        }
      }
      try {
        const runs = await listRuns()
        if (alive) setRunsBySlug(latestRunBySlug(Array.isArray(runs) ? runs : runs.results || []))
      } catch {
        /* runs are ornament only */
      }
    }
    load()
    const t = setInterval(load, 5000) // pick up agent-created tables live
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">WORKSPACE</div>
          <h1 className="page-title">Tables</h1>
        </div>
      </div>

      {error && <div className="error-note">{error}</div>}

      {tables && tables.length === 0 && !error ? (
        <div className="empty-state">
          NO TABLES YET — ASK THE AGENT TO SIFT YOUR SOURCES.
        </div>
      ) : (
        <div className="card-grid">
          {(tables || []).map((t) => (
            <TableCard
              key={t.slug}
              table={t}
              lastRun={runsBySlug[t.slug]}
              onOpen={() => onOpenTable(t.slug)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
