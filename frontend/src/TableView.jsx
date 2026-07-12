import { useEffect, useRef, useState } from 'react'
import { getTable, listRecords, updateRecord } from './api.js'
import { SourceBadge } from './ui.jsx'
import { humanizeTs } from './format.js'

function cellContent(col, value) {
  if (value == null || value === '') return <span className="cell-null">—</span>
  if (col.type === 'bool') return value ? 'true' : 'false'
  return String(value)
}

// Per-row provenance: source badge opening a small popover with
// source + external_id + ts for each provenance entry.
function ProvenanceCell({ record, open, onToggle }) {
  const sources = record.sources || []
  const popRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => {
      if (popRef.current && !popRef.current.contains(e.target)) onToggle(null)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open, onToggle])

  if (sources.length === 0) return <span className="cell-null">—</span>

  const primary = sources[0]
  return (
    <span className="prov-wrap" ref={popRef}>
      <SourceBadge
        source={primary.source}
        onClick={() => onToggle(open ? null : record.id)}
      />
      {sources.length > 1 && <span className="prov-more">+{sources.length - 1}</span>}
      {open && (
        <div className="prov-pop">
          {sources.map((s, i) => (
            <div key={`${s.source}-${s.external_id}-${i}`} className="prov-entry">
              <SourceBadge source={s.source} />
              <div className="prov-id">{s.external_id}</div>
              <div className="prov-ts">{s.ts ? new Date(s.ts).toLocaleString() : '—'}</div>
            </div>
          ))}
        </div>
      )}
    </span>
  )
}

// Inline cell editor: double-click a cell, Enter/blur commits, Esc cancels.
function CellEditor({ initial, onCommit, onCancel, saving }) {
  const [value, setValue] = useState(initial)
  const inputRef = useRef(null)

  useEffect(() => {
    const el = inputRef.current
    if (el) {
      el.focus()
      el.select()
    }
  }, [])

  return (
    <input
      ref={inputRef}
      className="cell-input"
      value={value}
      disabled={saving}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onCommit(value)
        else if (e.key === 'Escape') onCancel()
      }}
      onBlur={() => onCommit(value)}
    />
  )
}

export default function TableView({ slug, onBack }) {
  const [table, setTable] = useState(null)
  const [records, setRecords] = useState(null) // null = loading
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [openProv, setOpenProv] = useState(null)
  const [edit, setEdit] = useState(null) // {recordId, col}
  const [saving, setSaving] = useState(false)
  const searchRef = useRef(search)
  searchRef.current = search
  const editRef = useRef(edit)
  editRef.current = edit

  // Table schema — once per slug.
  useEffect(() => {
    let alive = true
    setTable(null)
    setRecords(null)
    setError('')
    getTable(slug)
      .then((t) => alive && setTable(t))
      .catch((e) => alive && setError(`could not load table — ${e.message}`))
    return () => {
      alive = false
    }
  }, [slug])

  // Records — ?search= wired to the API, polled so pipeline runs show up live.
  useEffect(() => {
    let alive = true
    const load = async () => {
      if (editRef.current) return // don't clobber an in-progress cell edit
      try {
        const data = await listRecords(slug, searchRef.current)
        if (alive) {
          setRecords(Array.isArray(data) ? data : data.results || [])
          setError('')
        }
      } catch (e) {
        if (alive) {
          setError(`could not load records — ${e.message}`)
          setRecords((prev) => prev || [])
        }
      }
    }
    const debounce = setTimeout(load, 250)
    const poll = setInterval(load, 5000)
    return () => {
      alive = false
      clearTimeout(debounce)
      clearInterval(poll)
    }
  }, [slug, search])

  const columns = table?.columns || []
  const dedupeKeys = table?.dedupe_keys || []

  const commitEdit = async (record, col, raw) => {
    if (saving) return // blur can re-fire while the PATCH is in flight
    const current = (record.data || {})[col.name]
    const next = raw.trim()
    // No-op edits just close the editor.
    if (next === String(current ?? '')) {
      setEdit(null)
      return
    }
    setSaving(true)
    try {
      const updated = await updateRecord(slug, record.id, { [col.name]: next === '' ? null : next })
      setRecords((prev) => (prev || []).map((r) => (r.id === updated.id ? updated : r)))
      setError('')
      setEdit(null)
    } catch (e) {
      setError(`could not save ${col.name} — ${e.message}`)
      // keep the editor open so the value isn't lost
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <button className="back-link" onClick={onBack}>
            ← TABLES
          </button>
          <h1 className="page-title">{table ? table.name : slug}</h1>
          {table && (
            <span className="page-sub mono">
              {table.record_count ?? 0} rows · {columns.length} cols
              {dedupeKeys.length > 0 ? ` · dedupe on ${dedupeKeys.join(', ')}` : ''}
            </span>
          )}
        </div>
        <input
          className="search-box"
          placeholder="search rows…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {error && <div className="error-note">{error}</div>}

      {records && records.length === 0 && !error ? (
        <div className="empty-state">
          {search
            ? `NO ROWS MATCH “${search.toUpperCase()}”.`
            : 'NO ROWS YET — ASK THE AGENT TO SIFT YOUR SOURCES.'}
        </div>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.name} className={c.type === 'number' ? 'num' : ''}>
                    {c.name}
                    {dedupeKeys.includes(c.name) && (
                      <span className="key-mark" title="dedupe key">
                        ▪
                      </span>
                    )}
                  </th>
                ))}
                <th>SOURCE</th>
                <th className="num">UPDATED</th>
              </tr>
            </thead>
            <tbody>
              {(records || []).map((r) => (
                <tr key={r.id}>
                  {columns.map((c) => {
                    const isEditing = edit && edit.recordId === r.id && edit.col === c.name
                    return (
                      <td
                        key={c.name}
                        className={`${c.type === 'number' ? 'num' : ''} cell-editable`}
                        title={isEditing ? '' : 'double-click to edit'}
                        onDoubleClick={() => !isEditing && setEdit({ recordId: r.id, col: c.name })}
                      >
                        {isEditing ? (
                          <CellEditor
                            initial={String((r.data || {})[c.name] ?? '')}
                            saving={saving}
                            onCommit={(v) => commitEdit(r, c, v)}
                            onCancel={() => setEdit(null)}
                          />
                        ) : (
                          cellContent(c, (r.data || {})[c.name])
                        )}
                      </td>
                    )
                  })}
                  <td>
                    <ProvenanceCell
                      record={r}
                      open={openProv === r.id}
                      onToggle={setOpenProv}
                    />
                  </td>
                  <td className="num muted mono">{humanizeTs(r.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
