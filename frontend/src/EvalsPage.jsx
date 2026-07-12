import { useEffect, useState } from 'react'
import { getEvals } from './api.js'

const SUITE_LABELS = {
  system: 'System prompt',
  skills: 'Skills',
  system_prompt: 'System prompt',
}

// score → semantic color band (mirrors Langfuse's read: pass / warn / fail).
function band(v) {
  if (v >= 0.8) return 'ok'
  if (v >= 0.5) return 'warn'
  return 'err'
}

function pct(v) {
  return `${Math.round((v ?? 0) * 100)}%`
}

function ScoreBar({ value }) {
  return (
    <div className="eval-bar">
      <div className={`eval-bar-fill eval-${band(value)}`} style={{ width: pct(value) }} />
    </div>
  )
}

function SuiteCard({ suiteKey, suite, url }) {
  return (
    <div className="card eval-suite">
      <div className="eval-suite-head">
        <h2 className="card-title">{SUITE_LABELS[suiteKey] || suiteKey}</h2>
        <span className={`eval-score-pill eval-${band(suite.overall)}`}>{pct(suite.overall)}</span>
        {url && (
          <a className="eval-run-link" href={url} target="_blank" rel="noreferrer">
            LANGFUSE RUN →
          </a>
        )}
      </div>
      <div className="eval-dims">
        {suite.dimensions.map((d) => (
          <div key={d.name} className="eval-dim">
            <span className="eval-dim-name" title={`${d.n} case${d.n === 1 ? '' : 's'}`}>
              {d.name}
            </span>
            <ScoreBar value={d.avg} />
            <span className={`eval-dim-val eval-${band(d.avg)}`}>{pct(d.avg)}</span>
            <span className="eval-dim-n mono muted">n={d.n}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function History({ history }) {
  if (!history || history.length < 2) return null
  const max = Math.max(...history.map((h) => h.overall ?? 0), 1)
  return (
    <div className="card eval-history">
      <div className="eval-suite-head">
        <h2 className="card-title">Runs over time</h2>
        <span className="mono muted" style={{ fontSize: 11 }}>{history.length} runs</span>
      </div>
      <div className="eval-trend">
        {[...history].reverse().map((h, i) => (
          <div key={`${h.file || i}`} className="eval-trend-col" title={`${pct(h.overall)} · prompt ${h.prompt_hash} · ${h.git_sha}`}>
            <div
              className={`eval-trend-bar eval-${band(h.overall)}`}
              style={{ height: `${((h.overall ?? 0) / max) * 100}%` }}
            />
            <span className="eval-trend-label mono muted">{h.prompt_hash?.slice(0, 4)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function EvalsPage() {
  const [data, setData] = useState(null) // null = loading
  const [error, setError] = useState('')

  const load = async () => {
    try {
      const d = await getEvals()
      setData(d)
      setError('')
    } catch (e) {
      setError(`could not reach the api — ${e.message}`)
      setData((prev) => prev || { latest: null, history: [] })
    }
  }

  useEffect(() => {
    load()
  }, [])

  const latest = data && data.latest

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">QUALITY · LANGFUSE</div>
          <h1 className="page-title">Evals</h1>
        </div>
        <button className="btn" onClick={load}>
          REFRESH
        </button>
      </div>

      {error && <div className="error-note">{error}</div>}

      {data && !latest && !error && (
        <div className="empty-state">
          NO EVAL RUNS YET — RUN{' '}
          <span className="mono">backend/.venv/bin/python backend/evals/run_evals.py all</span>
        </div>
      )}

      {latest && (
        <>
          <div className="eval-summary">
            <div className="eval-overall">
              <span className={`eval-overall-num eval-${band(latest.overall)}`}>
                {pct(latest.overall)}
              </span>
              <span className="eval-overall-label">OVERALL</span>
            </div>
            <div className="eval-meta">
              <span className="eval-tag">
                client <b>{latest.client}</b>
              </span>
              <span className="eval-tag">
                langfuse <b>{latest.langfuse ? 'on' : 'off'}</b>
              </span>
              <span className="eval-tag">
                prompt <b className="mono">{latest.prompt_hash}</b>
              </span>
              <span className="eval-tag">
                git <b className="mono">{latest.git_sha}</b>
              </span>
              {latest.ran_at && (
                <span className="eval-tag muted">{new Date(latest.ran_at).toLocaleString()}</span>
              )}
            </div>
          </div>

          <div className="eval-grid">
            {Object.entries(latest.suites).map(([key, suite]) => (
              <SuiteCard
                key={key}
                suiteKey={key}
                suite={suite}
                url={latest.urls && (latest.urls[key] || latest.urls[key.replace('_prompt', '')])}
              />
            ))}
          </div>

          <History history={data.history} />
        </>
      )}
    </div>
  )
}
