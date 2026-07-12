import { useState } from 'react'
import ContactsPage from './ContactsPage.jsx'
import WorkflowsPage from './WorkflowsPage.jsx'
import ConnectionsPage from './ConnectionsPage.jsx'
import ChatPanel from './ChatPanel.jsx'

const NAV = [
  { key: 'contacts', label: 'Contacts', icon: '👥' },
  { key: 'workflows', label: 'Workflows', icon: '⚡' },
  { key: 'connections', label: 'Connections', icon: '🔌' },
]

export default function App() {
  const [page, setPage] = useState('contacts')

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            ⚕
          </div>
          <div>
            Caduceus
            <small>Agentic CRM</small>
          </div>
        </div>
        {NAV.map((n) => (
          <button
            key={n.key}
            className={`nav-item ${page === n.key ? 'active' : ''}`}
            onClick={() => setPage(n.key)}
          >
            <span className="nav-icon" aria-hidden="true">
              {n.icon}
            </span>
            {n.label}
          </button>
        ))}
        <div className="sidebar-foot">hermes-4 · local</div>
      </nav>

      <main className="main">
        {page === 'contacts' && <ContactsPage />}
        {page === 'workflows' && <WorkflowsPage />}
        {page === 'connections' && <ConnectionsPage />}
      </main>

      <ChatPanel onNavigate={setPage} />
    </div>
  )
}
