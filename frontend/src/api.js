// Thin fetch helpers for every endpoint in CONTRACTS.md.

async function request(path, options = {}) {
  const res = await fetch(path, {
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

// ---- Contacts / interactions ----
export const listContacts = (search = '') =>
  request(`/api/contacts/${search ? `?search=${encodeURIComponent(search)}` : ''}`)

export const getContact = (id) => request(`/api/contacts/${id}/`)

export const listInteractions = (contactId) =>
  request(`/api/interactions/?contact=${encodeURIComponent(contactId)}`)

// ---- Workflows / runs ----
export const listWorkflows = () => request('/api/workflows/')

export const createWorkflow = (name, dsl) =>
  request('/api/workflows/', { method: 'POST', body: JSON.stringify({ name, dsl }) })

export const runWorkflow = (id) => request(`/api/workflows/${id}/run/`, { method: 'POST' })

export const listRuns = () => request('/api/runs/')

export const getRun = (id) => request(`/api/runs/${id}/`)

// ---- Connections ----
export const listConnections = () => request('/api/connections/')

export const pairWhatsapp = () =>
  request('/api/connections/whatsapp/pair/', { method: 'POST' })

export const connectGmail = () =>
  request('/api/connections/gmail/connect/', { method: 'POST' })

// ---- Agent chat (SSE over fetch) ----
// streamChat(message, chatId, onEvent)
// onEvent({type: 'token'|'tool'|'workflow_created'|'run_started'|'done', data})
export async function streamChat(message, chatId, onEvent) {
  const res = await fetch('/api/agent/chat', {
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
