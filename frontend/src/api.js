// Thin fetch helpers for every endpoint in CONTRACTS.md (v2).

// Base URL for the API. Empty locally (Vite proxies /api → :8000); on
// Cloudflare Pages set VITE_API_BASE to the Worker URL that fronts the
// Django container, e.g. https://sift-api.<subdomain>.workers.dev
const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    let detail = ''
    try {
      detail = await res.text()
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? ` — ${detail.slice(0, 200)}` : ''}`)
  }
  if (res.status === 204) return null
  return res.json()
}

// ---- Tables / records ----
export const listTables = () => request('/api/tables/')

export const createTable = (name, columns, dedupeKeys) =>
  request('/api/tables/', {
    method: 'POST',
    body: JSON.stringify({ name, columns, dedupe_keys: dedupeKeys }),
  })

export const getTable = (slug) => request(`/api/tables/${encodeURIComponent(slug)}/`)

export const listRecords = (slug, search = '') =>
  request(
    `/api/tables/${encodeURIComponent(slug)}/records/${
      search ? `?search=${encodeURIComponent(search)}` : ''
    }`,
  )

export const updateRecord = (slug, recordId, data) =>
  request(`/api/tables/${encodeURIComponent(slug)}/records/${recordId}/`, {
    method: 'PATCH',
    body: JSON.stringify({ data }),
  })

// ---- Workflows / runs ----
export const listWorkflows = () => request('/api/workflows/')

export const createWorkflow = (name, dsl) =>
  request('/api/workflows/', { method: 'POST', body: JSON.stringify({ name, dsl }) })

export const updateWorkflow = (id, patch) =>
  request(`/api/workflows/${id}/`, { method: 'PATCH', body: JSON.stringify(patch) })

export const runWorkflow = (id) => request(`/api/workflows/${id}/run/`, { method: 'POST' })

export const listRuns = () => request('/api/runs/')

export const getRun = (id) => request(`/api/runs/${id}/`)

// ---- Chats (history) ----
export const listChats = () => request('/api/chats/')

export const getChatMessages = (chatId) =>
  request(`/api/chats/${encodeURIComponent(chatId)}/messages/`)

// ---- Evals ----
export const getEvals = () => request('/api/evals/')

// ---- Connections ----
export const listConnections = () => request('/api/connections/')

export const pairWhatsapp = (phone) =>
  request('/api/connections/whatsapp/pair/', {
    method: 'POST',
    body: JSON.stringify(phone ? { phone } : {}),
  })

export const connectGmail = () =>
  request('/api/connections/gmail/connect/', { method: 'POST' })

export const disconnectSource = (source) =>
  request(`/api/connections/${source}/disconnect/`, { method: 'POST' })

// ---- WhatsApp chat scoping ----
export const listWhatsappChats = () => request('/api/whatsapp/chats/')

export const scopeWhatsappChat = (id, scoped) =>
  request(`/api/whatsapp/chats/${id}/scope/`, {
    method: 'POST',
    body: JSON.stringify({ scoped }),
  })

// ---- Agent chat (SSE over fetch) ----
// streamChat(message, chatId, onEvent)
// onEvent({type: 'token'|'tool'|'table_created'|'workflow_created'|'run_started'|'done', data})
export async function streamChat(message, chatId, onEvent) {
  const res = await fetch(BASE + '/api/agent/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, chat_id: chatId || null }),
  })
  if (!res.ok || !res.body) {
    throw new Error(`agent chat failed: ${res.status} ${res.statusText}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (rawBlock) => {
    // An SSE event block: lines of "event: X" / "data: Y"
    let eventType = 'message'
    const dataLines = []
    for (const line of rawBlock.split('\n')) {
      if (line.startsWith('event:')) eventType = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    }
    if (!dataLines.length) return
    let data = dataLines.join('\n')
    try {
      data = JSON.parse(data)
    } catch {
      /* leave as raw string */
    }
    onEvent({ type: eventType, data })
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // Events are separated by a blank line.
    let idx
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      if (block.trim()) dispatch(block)
    }
  }
  if (buffer.trim()) dispatch(buffer)
}
