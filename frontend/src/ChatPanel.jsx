import { useEffect, useRef, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { streamChat, listChats, getChatMessages } from './api.js'

marked.setOptions({ gfm: true, breaks: true })

// Agent bubbles render markdown; sanitized since the text comes from the LLM.
function Markdown({ text }) {
  const html = DOMPurify.sanitize(marked.parse(text || ''))
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />
}

const SUGGESTIONS = [
  'Track everyone asking about pricing in my WhatsApp chats',
  'Build a table of invoices from my Gmail',
  'What tables do I have, and how many rows in each?',
]

let nextId = 1
const uid = () => nextId++

// Compact one-line rendering of tool args: name-ish value or short JSON.
function summarizeArgs(args) {
  if (!args || typeof args !== 'object') return ''
  const key = args.name ?? args.table ?? args.workflow_id ?? args.path ?? null
  if (key != null) return String(key)
  try {
    const s = JSON.stringify(args)
    return s === '{}' ? '' : s.length > 48 ? `${s.slice(0, 48)}…` : s
  } catch {
    return ''
  }
}

// `table_created` → schema-chip card: column name+type chips, dedupe keys marked.
function SchemaCard({ table, onNavigate }) {
  const dedupe = table.dedupe_keys || []
  return (
    <div className="schema-card">
      <div className="schema-card-title">table created — {table.name}</div>
      <div className="chip-row">
        {(table.columns || []).map((c) => (
          <span
            key={c.name}
            className={`schema-chip ${dedupe.includes(c.name) ? 'schema-chip-key' : ''}`}
            title={dedupe.includes(c.name) ? 'dedupe key' : c.description || ''}
          >
            {c.name}
            <em>{c.type}</em>
            {dedupe.includes(c.name) && <span className="key-mark">▪</span>}
          </span>
        ))}
      </div>
      <button
        className="schema-open"
        onClick={() => onNavigate && onNavigate('table', table.slug)}
      >
        OPEN TABLE →
      </button>
    </div>
  )
}

// One mono chip per DSL step, with its most useful parameter inlined.
function stepLabel(step) {
  if (!step || !step.type) return null
  if (step.type === 'fetch') {
    const window =
      step.since_days != null
        ? `${step.since_days}d`
        : [step.from_date, step.to_date].filter(Boolean).join('→') || null
    return [step.type, step.source, window].filter(Boolean).join(' · ')
  }
  if (step.type === 'upsert' && Array.isArray(step.dedupe_on) && step.dedupe_on.length) {
    return `upsert · key ${step.dedupe_on.join(', ')}`
  }
  return step.type
}

// `workflow_created` → card bubble: name, DSL step chain, table + trigger meta.
function WorkflowCard({ workflow, onNavigate }) {
  const dsl = workflow?.dsl || {}
  const steps = Array.isArray(dsl.steps) ? dsl.steps : []
  const trigger =
    dsl.trigger && typeof dsl.trigger === 'object'
      ? `every ${dsl.trigger.minutes}m`
      : dsl.trigger || 'manual'
  return (
    <div className="wf-card">
      <div className="wf-card-title">⚡ workflow created — {workflow?.name}</div>
      {steps.length > 0 && (
        <div className="wf-chain">
          {steps.map((s, i) => (
            <span key={i} className="wf-chain-item">
              {i > 0 && <span className="wf-arrow">→</span>}
              <span
                className="wf-step"
                title={s.type === 'filter' ? s.instruction || '' : ''}
              >
                {stepLabel(s)}
              </span>
            </span>
          ))}
        </div>
      )}
      <div className="wf-meta">
        {dsl.table ? `TABLE ${dsl.table} · ` : ''}TRIGGER {String(trigger).toUpperCase()}
      </div>
      <button className="schema-open" onClick={() => onNavigate && onNavigate('workflows')}>
        VIEW WORKFLOWS →
      </button>
    </div>
  )
}

export default function ChatPanel({ onNavigate }) {
  // items: {id, kind: 'user'|'agent'|'tool'|'table'|'workflow'|'run', ...}
  const [items, setItems] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [chatId, setChatId] = useState(null)
  // null = history endpoint absent (backend not there yet) → hide the UI
  const [chats, setChats] = useState(null)
  const [showHistory, setShowHistory] = useState(false)
  const scrollRef = useRef(null)
  const stickRef = useRef(true) // stick to bottom unless the user scrolled up
  const chatIdRef = useRef(null)
  chatIdRef.current = chatId

  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [items])

  const onScroll = (e) => {
    const el = e.currentTarget
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  const refreshChats = async () => {
    try {
      const data = await listChats()
      setChats(Array.isArray(data) ? data : data.results || [])
    } catch {
      setChats(null) // endpoint not implemented yet — keep history UI hidden
    }
  }

  useEffect(() => {
    refreshChats()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const resumeChat = async (chat) => {
    setShowHistory(false)
    try {
      const data = await getChatMessages(chat.chat_id)
      const msgs = Array.isArray(data) ? data : data.results || []
      stickRef.current = true
      setItems(
        msgs
          .filter((m) => (m.content || '').trim() !== '')
          .map((m) => ({
            id: uid(),
            kind: m.role === 'user' ? 'user' : 'agent',
            text: m.content,
          })),
      )
      setChatId(chat.chat_id)
    } catch (e) {
      setItems((prev) => [
        ...prev,
        { id: uid(), kind: 'agent', text: `could not load that conversation — ${e.message}` },
      ])
    }
  }

  const newChat = () => {
    setShowHistory(false)
    setItems([])
    setChatId(null)
  }

  const send = async (text) => {
    const message = (text || '').trim()
    if (!message || busy) return
    setInput('')
    setBusy(true)

    const agentMsgId = uid()
    setItems((prev) => [
      ...prev,
      { id: uid(), kind: 'user', text: message },
      { id: agentMsgId, kind: 'agent', text: '', streaming: true },
    ])

    // Streaming may interleave text and events; each event that isn't a token
    // closes the current agent bubble and a fresh one is opened for later tokens.
    let currentAgentId = agentMsgId

    const appendItem = (item) => {
      const newAgentId = uid()
      setItems((prev) => {
        const closed = prev.map((it) =>
          it.id === currentAgentId ? { ...it, streaming: false } : it,
        )
        return [...closed, item, { id: newAgentId, kind: 'agent', text: '', streaming: true }]
      })
      currentAgentId = newAgentId
    }

    try {
      await streamChat(message, chatIdRef.current, (ev) => {
        if (ev.type === 'token') {
          setItems((prev) =>
            prev.map((it) =>
              it.id === currentAgentId ? { ...it, text: it.text + (ev.data.text || '') } : it,
            ),
          )
        } else if (ev.type === 'tool') {
          appendItem({ id: uid(), kind: 'tool', name: ev.data.name, args: ev.data.args })
        } else if (ev.type === 'table_created') {
          appendItem({ id: uid(), kind: 'table', table: ev.data.table })
        } else if (ev.type === 'workflow_created') {
          appendItem({ id: uid(), kind: 'workflow', workflow: ev.data.workflow })
        } else if (ev.type === 'run_started') {
          appendItem({
            id: uid(),
            kind: 'run',
            runId: ev.data.run_id,
            workflowId: ev.data.workflow_id,
          })
        } else if (ev.type === 'done') {
          if (ev.data && ev.data.chat_id) setChatId(ev.data.chat_id)
        }
      })
    } catch (e) {
      setItems((prev) =>
        prev.map((it) =>
          it.id === currentAgentId
            ? { ...it, text: it.text || `agent unavailable — ${e.message}` }
            : it,
        ),
      )
    } finally {
      // Close any open bubble and drop empty ones.
      setItems((prev) =>
        prev
          .map((it) => (it.kind === 'agent' ? { ...it, streaming: false } : it))
          .filter((it) => !(it.kind === 'agent' && it.text.trim() === '')),
      )
      setBusy(false)
      refreshChats()
    }
  }

  return (
    <aside className="chat-panel">
      <div className="chat-head">
        <span className="dot" />
        <div>
          <div className="chat-head-title">agent</div>
          <div className="chat-head-sub">{chatId ? `chat ${chatId}` : 'new conversation'}</div>
        </div>
        {(chats !== null || chatId || items.length > 0) && (
          <span className="chat-head-actions">
            {(chatId || items.length > 0) && (
              <button className="flow-toggle" onClick={newChat} disabled={busy}>
                NEW
              </button>
            )}
            {chats !== null && chats.length > 0 && (
              <button
                className="flow-toggle"
                onClick={() => setShowHistory((v) => !v)}
                aria-expanded={showHistory}
              >
                HISTORY
              </button>
            )}
          </span>
        )}
      </div>

      {showHistory && chats && (
        <div className="chat-history">
          {chats.map((c) => (
            <button key={c.chat_id} className="chat-history-item" onClick={() => resumeChat(c)}>
              <span className="chat-history-title">{c.title || c.chat_id}</span>
              <span className="chat-history-meta">
                {c.message_count != null ? `${c.message_count} msgs` : ''}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        {items.length === 0 ? (
          <div className="chat-empty">
            <div className="chat-empty-mark" aria-hidden="true" />
            <p>
              describe what you want to track. the agent designs the table, builds the pipeline,
              and sifts your sources into rows.
            </p>
            {SUGGESTIONS.map((s) => (
              <button key={s} className="prompt-chip" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        ) : (
          items.map((it) => {
            if (it.kind === 'user' || it.kind === 'agent') {
              if (it.kind === 'agent' && it.text.trim() === '') {
                // whitespace-only bubbles (a stray "\n" token between tool calls)
                // render as empty ghosts — show only the live one with its cursor
                if (!it.streaming) return null
                return (
                  <div key={it.id} className="msg msg-agent">
                    <div className="bubble bubble-cursor-only">
                      <span className="cursor" />
                    </div>
                  </div>
                )
              }
              return (
                <div key={it.id} className={`msg msg-${it.kind}`}>
                  <div className="bubble">
                    {it.kind === 'agent' ? <Markdown text={it.text} /> : it.text}
                    {it.streaming && <span className="cursor" />}
                  </div>
                </div>
              )
            }
            if (it.kind === 'tool') {
              const args = summarizeArgs(it.args)
              return (
                <div key={it.id} className="sys-line" title={JSON.stringify(it.args)}>
                  ⚙ {it.name}({args}) …
                </div>
              )
            }
            if (it.kind === 'table') {
              return <SchemaCard key={it.id} table={it.table} onNavigate={onNavigate} />
            }
            if (it.kind === 'workflow') {
              return <WorkflowCard key={it.id} workflow={it.workflow} onNavigate={onNavigate} />
            }
            if (it.kind === 'run') {
              return (
                <button
                  key={it.id}
                  className="sys-line sys-line-link"
                  onClick={() => onNavigate && onNavigate('workflows')}
                >
                  ▶ run {String(it.runId).padStart(4, '0')} started →
                </button>
              )
            }
            return null
          })
        )}
      </div>

      <div className="chat-input-row">
        <input
          className="chat-input"
          placeholder="ask the agent…"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
        />
        <button className="chat-send" onClick={() => send(input)} disabled={busy || !input.trim()}>
          {busy ? '…' : 'SEND'}
        </button>
      </div>
    </aside>
  )
}
