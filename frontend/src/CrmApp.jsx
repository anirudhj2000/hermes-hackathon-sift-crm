import { useEffect, useState } from 'react'
import { listTables } from './api.js'
import TablesPage from './TablesPage.jsx'
import TableView from './TableView.jsx'
import WorkflowsPage from './WorkflowsPage.jsx'
import ConnectionsPage from './ConnectionsPage.jsx'
import EvalsPage from './EvalsPage.jsx'
import AccountPage from './AccountPage.jsx'
import ChatPanel from './ChatPanel.jsx'

const NAV = [
  { key: 'tables', label: 'TABLES' },
  { key: 'workflows', label: 'WORKFLOWS' },
  { key: 'connections', label: 'CONNECTIONS' },
  { key: 'evals', label: 'EVALS' },
  { key: 'account', label: 'ACCOUNT' },
]

// #/app            → tables (default)
// #/app/tables/x   → table view for slug x
// #/app/workflows | connections | evals | account → those pages
function parseRoute() {
  const parts = window.location.hash.replace(/^#\/?/, '').split('/')
  const section = parts[1] || 'tables'
  if (['workflows', 'connections', 'evals', 'account'].includes(section)) {
    return { page: section, slug: null }
  }
  if (section === 'tables' && parts[2]) {
    return { page: 'table', slug: decodeURIComponent(parts[2]) }
  }
  return { page: 'tables', slug: null }
}

function navigate(page, slug = null) {
  window.location.hash =
    page === 'table' && slug
      ? `#/app/tables/${encodeURIComponent(slug)}`
      : `#/app/${page === 'tables' ? 'tables' : page}`
}

export default function CrmApp({ user }) {
  const [route, setRoute] = useState(parseRoute)
  const [tables, setTables] = useState([])

  useEffect(() => {
    const onHash = () => setRoute(parseRoute())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // Sidebar table list — polled so agent-created tables appear without a reload.
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const data = await listTables()
        if (alive) setTables(Array.isArray(data) ? data : data.results || [])
      } catch {
        /* sidebar list is best-effort */
      }
    }
    load()
    const poll = setInterval(load, 5000)
    return () => {
      alive = false
      clearInterval(poll)
    }
  }, [])

  const activeKey = route.page === 'table' ? 'tables' : route.page

  return (
    <div className="crm">
      <div className="shell">
        <nav className="sidebar">
          <a className="brand" href="#/">
            sift
            <span className="brand-dot" aria-hidden="true" />
          </a>
          <div className="nav-label">WORKSPACE</div>
          {NAV.map((n) => (
            <div key={n.key}>
              <button
                className={`nav-item ${activeKey === n.key ? 'active' : ''}`}
                onClick={() => navigate(n.key)}
              >
                {n.label}
              </button>
              {n.key === 'tables' && tables.length > 0 && (
                <div className="nav-sub">
                  {tables.map((t) => (
                    <button
                      key={t.slug}
                      className={`nav-sub-item ${
                        route.page === 'table' && route.slug === t.slug ? 'active' : ''
                      }`}
                      onClick={() => navigate('table', t.slug)}
                    >
                      <span className="nav-sub-tick" aria-hidden="true">└</span>
                      {t.name}
                      <span className="nav-sub-count">{t.record_count ?? 0}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
          <div className="sidebar-foot">hermes-4 · local</div>
        </nav>

        <main className="main">
          {route.page === 'tables' && <TablesPage onOpenTable={(slug) => navigate('table', slug)} />}
          {route.page === 'table' && (
            <TableView slug={route.slug} onBack={() => navigate('tables')} />
          )}
          {route.page === 'workflows' && (
            <WorkflowsPage onOpenTable={(slug) => navigate('table', slug)} />
          )}
          {route.page === 'connections' && <ConnectionsPage />}
          {route.page === 'evals' && <EvalsPage />}
          {route.page === 'account' && <AccountPage user={user} />}
        </main>

        <ChatPanel onNavigate={navigate} />
      </div>
    </div>
  )
}
