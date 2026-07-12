import './landing.css'

const GITHUB_URL = 'https://github.com/anirudhj2000/hermes-hackathon-sift-crm'

const OFFERINGS = [
  {
    title: 'Agent-designed tables',
    body: 'Describe what you want to track in chat — leads, orders, job applicants, anything. The agent authors the schema: columns, types, and dedupe keys. Your CRM takes whatever shape your work does.',
    meta: 'SCHEMA · 5 COLS · KEY order_id',
  },
  {
    title: 'Agent-built pipelines',
    body: 'The agent designs the ingestion workflow as a stored, re-runnable JSON DSL — fetch → filter → extract → upsert into your table — then runs it. No integration screens, no field mapping.',
    meta: 'DSL v1 · 4 STEPS',
  },
  {
    title: 'WhatsApp ingestion',
    body: 'Pair your account by scanning a QR code; a Baileys sidecar keeps the session alive. New messages arrive over a live webhook and flow straight into the pipeline.',
    meta: 'SRC WHATSAPP · QR PAIR · LIVE WEBHOOK',
  },
  {
    title: 'Gmail ingestion',
    body: 'Connect Gmail through Composio hosted OAuth — no token plumbing on your side. Threads are fetched, filtered, and sifted alongside your chats.',
    meta: 'SRC GMAIL · COMPOSIO OAUTH',
  },
  {
    title: 'Schema-driven extraction',
    body: 'An LLM reads each raw message and turns it into a typed row of your schema — not a generic contact card. Every row keeps a link back to its source message, so provenance is one click away.',
    meta: '92 MSGS → 27 ROWS',
  },
  {
    title: 'MCP access',
    body: 'A FastMCP server exposes your tables to any MCP client — Claude, Cursor, your own agents. Five tools: list_tables, get_schema, query_records, upsert_record, run_workflow.',
    meta: '5 TOOLS · FASTMCP',
  },
]

const STEPS = [
  {
    n: '01',
    title: 'Ask',
    body: 'Type what you want: “track orders from my WhatsApp chats.”',
  },
  {
    n: '02',
    title: 'Agent designs',
    body: 'It drafts the table schema and the pipeline, and shows both for your approval before anything runs.',
  },
  {
    n: '03',
    title: 'Pipeline runs',
    body: 'fetch → filter → extract → upsert. Messages stream in; the LLM extracts per your schema.',
  },
  {
    n: '04',
    title: 'Your table fills itself',
    body: 'Rows, typed columns, provenance links — appearing without a single form.',
  },
]

export default function Landing() {
  return (
    <div className="sift">
      <header className="sl-nav">
        <a className="sl-wordmark" href="#top" aria-label="Sift home">
          sift<span className="sl-dot" aria-hidden="true" />
        </a>
        <nav className="sl-nav-links" aria-label="Landing sections">
          <a href="#offerings">Offerings</a>
          <a href="#how">How it works</a>
          <a href="#mcp">MCP</a>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">
            GitHub
          </a>
        </nav>
        <a className="sl-btn sl-btn-primary" href="#/app">
          Open Sift <span className="sl-arr" aria-hidden="true">→</span>
        </a>
      </header>

      <main id="top">
        {/* ---- HERO ---- */}
        <section className="sl-hero" aria-labelledby="hero-title">
          <div className="sl-hero-inner">
            <div className="sl-hero-copy">
              <p className="sl-eyebrow sl-fade" style={{ '--d': '0ms' }}>
                Sift — Agentic CRM
              </p>
              <h1 id="hero-title" className="sl-fade" style={{ '--d': '60ms' }}>
                Your conversations are already structured data. Sift finds the table.
              </h1>
              <p className="sl-sub sl-fade" style={{ '--d': '120ms' }}>
                Nobody updates their CRM. Now nobody has to.
              </p>
              <div className="sl-cta-row sl-fade" style={{ '--d': '180ms' }}>
                <a className="sl-btn sl-btn-primary" href="#/app">
                  Open Sift <span className="sl-arr" aria-hidden="true">→</span>
                </a>
                <a
                  className="sl-btn sl-btn-secondary"
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  Read the architecture
                </a>
              </div>
              <p className="sl-meta sl-fade" style={{ '--d': '240ms' }}>
                RUN 0042 · 92 MSGS → 27 ROWS · TABLE orders
              </p>
            </div>

            <div className="sl-poster sl-fade" style={{ '--d': '300ms' }} aria-hidden="true">
              <span className="sl-poster-note sl-poster-tl">AGENTIC CRM</span>
              <span className="sl-poster-note sl-poster-tr">EST. 2026</span>
              <span className="sl-poster-word">SIFT</span>
              <span className="sl-poster-note sl-poster-bl">
                fetch → filter → extract → upsert
              </span>
              <span className="sl-poster-note sl-poster-br">RUN 0042</span>
            </div>
          </div>
        </section>

        {/* ---- OFFERINGS (cyanotype) ---- */}
        <section className="sl-paper" id="offerings" aria-labelledby="offerings-title">
          <div className="sl-col">
            <p className="sl-eyebrow sl-eyebrow-paper" id="offerings-title">
              Offerings — what Sift does
            </p>
            <ul className="sl-offer-grid">
              {OFFERINGS.map((o) => (
                <li key={o.title} className="sl-offer">
                  <h2>{o.title}</h2>
                  <p>{o.body}</p>
                  <p className="sl-offer-meta">{o.meta}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ---- HOW IT WORKS (dark) ---- */}
        <section className="sl-how" id="how" aria-labelledby="how-title">
          <div className="sl-col">
            <p className="sl-eyebrow" id="how-title">
              How it works
            </p>
            <ol className="sl-steps">
              {STEPS.map((s) => (
                <li key={s.n} className="sl-step">
                  <span className="sl-step-n">{s.n}</span>
                  <h2>{s.title}</h2>
                  <p>{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ---- MCP STRIP (dark) ---- */}
        <section className="sl-mcp" id="mcp" aria-labelledby="mcp-title">
          <div className="sl-col">
            <p className="sl-eyebrow" id="mcp-title">
              MCP — query your tables from anywhere
            </p>
            <div className="sl-term">
              <div className="sl-term-head">
                <span>claude · connected to sift via mcp</span>
                <span className="sl-term-ok">● LIVE</span>
              </div>
              <div className="sl-term-body">
                <p className="sl-term-user">
                  <span className="sl-term-who">you ›</span> which orders are still unpaid this
                  week?
                </p>
                <p className="sl-term-tool">
                  ⚙ query_records(table=orders, status=unpaid, since=7d) ✓
                </p>
                <p className="sl-term-agent">
                  <span className="sl-term-who">claude ›</span> 4 orders are still unpaid since
                  jul 5 — three came in over whatsapp, one by email. the oldest has been
                  waiting six days.
                </p>
              </div>
              <p className="sl-term-tools">
                list_tables · get_schema · query_records · upsert_record · run_workflow
              </p>
            </div>
          </div>
        </section>
      </main>

      <footer className="sl-footer">
        <div className="sl-col">
          <p>SIFT · BUILT AT THE HERMES BUILDATHON · JULY 12, 2026</p>
          <p className="sl-footer-stack">
            DJANGO/DRF · POSTGRES 16 · REACT · BAILEYS · COMPOSIO · FASTMCP · GPT-5 ⇄ HERMES ⇄
            SELF-HOSTED vLLM
          </p>
        </div>
      </footer>
    </div>
  )
}
