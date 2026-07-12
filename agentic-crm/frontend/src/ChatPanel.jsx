import { useEffect, useRef, useState } from 'react'
import { streamChat } from './api.js'
import { prettyDsl } from './format.js'

const SUGGESTIONS = [
  'Import my WhatsApp chats from the last week and add everyone asking about pricing',
  'Pull in my Gmail and merge contacts',
  'How many contacts do I have, and from which sources?',
]

let nextId = 1
const uid = () => nextId++

function MiniWorkflowCard({ workflow }) {
  return (
    <div className="mini-wf">
      <div className="mini-wf-title">
        <span aria-hidden="true">⚡</span> Workflow created — {workflow.name}
      </div>
      <pre>{prettyDsl(workflow.dsl)}</pre>
    </div>
  )
}

export default function ChatPanel({ onNavigate }) {
  const [items, setItems] = useState([]) // {id, kind: 'user'|'agent'|'tool'|'workflow'|'run', ...}
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [chatId, setChatId] = useState(null)
  const scrollRef = useRef(null)
  const chatIdRef = useRef(null)
  chatIdRef.current = chatId

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items])

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
            ? { ...it, text: it.text || `⚠ Agent unavailable: ${e.message}` }
            : it,
        ),
      )
    } finally {
      // Close any open bubble and drop empty ones.
      setItems((prev) =>
        prev
          .map((it) => (it.kind === 'agent' ? { ...it, streaming: false } : it))
          .filter((it) => !(it.kind === 'agent' && it.text === '')),
      )
      setBusy(false)
    }
  }

  const summarizeArgs = (args) => {
    if (!args || typeof args !== 'object') return ''
    const s = args.name || args.workflow_id || args.question || ''
    return s ? ` ${JSON.stringify(s)}` : ''
  }

  return (
    <aside className="chat-panel">
      <div className="chat-head">
        <span className="dot" />
        <div>
          <div className="chat-head-title">Hermes Agent</div>
          <div className="chat-head-sub">{chatId ? `chat ${chatId}` : 'new conversation'}</div>
        </div>
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {items.length === 0 ? (
          <div className="chat-empty">
            <div className="chat-empty-icon" aria-hidden="true">
              ⚕️
            </div>
            <p>
              Tell the agent what to pull into your CRM. It will design a workflow, show it to
              you, and run it.
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
              if (it.kind === 'agent' && it.text === '' && !it.streaming) return null
              return (
                <div key={it.id} className={`msg msg-${it.kind}`}>
                  <div className="bubble">
                    {it.text}
                    {it.streaming && <span className="cursor" />}
                  </div>
                </div>
              )
            }
            if (it.kind === 'tool') {
              return (
                <span key={it.id} className="sys-chip" title={JSON.stringify(it.args)}>
                  ⚙ {it.name}
                  {summarizeArgs(it.args)}
                </span>
              )
            }
            if (it.kind === 'workflow') {
              return <MiniWorkflowCard key={it.id} workflow={it.workflow} />
            }
            if (it.kind === 'run') {
              return (
                <button
                  key={it.id}
                  className="link-chip"
                  onClick={() => onNavigate && onNavigate('workflows')}
                >
                  ▶ Run #{it.runId} started
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
          placeholder="Ask the agent…"
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
          {busy ? '…' : 'Send'}
        </button>
      </div>
    </aside>
  )
}
