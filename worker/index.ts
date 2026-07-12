import { Container, getContainer } from '@cloudflare/containers'

export interface Env {
  DJANGO: DurableObjectNamespace<DjangoContainer>
  SIDECAR?: DurableObjectNamespace<SidecarContainer> // STAGE 2
  // secrets + vars (see wrangler.jsonc):
  DATABASE_URL: string
  HERMES_API_KEY: string
  HERMES_BASE_URL: string
  HERMES_MODEL: string
  COMPOSIO_API_KEY: string
  INGEST_SECRET: string
  SIDECAR_SECRET: string
  PUBLIC_URL: string
}

// Django + DRF + agent loop; listens on :8000 inside the container.
// gthread gunicorn (see backend/Dockerfile) so SSE /api/agent/chat streams.
export class DjangoContainer extends Container<Env> {
  defaultPort = 8000
  sleepAfter = '1h'
  // Field initializer (not a getter): the base declares envVars as a plain data
  // field, and `this.env` is already populated by super() when this runs.
  envVars = {
    DATABASE_URL: this.env.DATABASE_URL,
    HERMES_API_KEY: this.env.HERMES_API_KEY,
    HERMES_BASE_URL: this.env.HERMES_BASE_URL,
    HERMES_MODEL: this.env.HERMES_MODEL,
    COMPOSIO_API_KEY: this.env.COMPOSIO_API_KEY,
    INGEST_SECRET: this.env.INGEST_SECRET,
    SIDECAR_SECRET: this.env.SIDECAR_SECRET,
    // Django reaches the sidecar through this Worker's public URL.
    SIDECAR_URL: `${this.env.PUBLIC_URL}/_sidecar`,
  }
}

// Baileys WhatsApp bridge; listens on :3001. STAGE 2 (needs R2 auth adapter —
// container disk is ephemeral, so auth_state must persist to R2).
export class SidecarContainer extends Container<Env> {
  defaultPort = 3001
  sleepAfter = '2h'
  envVars = {
    INGEST_URL: `${this.env.PUBLIC_URL}/api/ingest/whatsapp`,
    INGEST_SECRET: this.env.INGEST_SECRET,
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url)

    // Internal Django → sidecar route, secret-gated so it isn't publicly usable.
    if (url.pathname.startsWith('/_sidecar/')) {
      if (!env.SIDECAR) return new Response('sidecar not deployed (stage 2)', { status: 503 })
      if (request.headers.get('x-sidecar-secret') !== env.SIDECAR_SECRET) {
        return new Response('forbidden', { status: 403 })
      }
      const inner = new URL(request.url)
      inner.pathname = url.pathname.replace(/^\/_sidecar/, '') || '/'
      return getContainer(env.SIDECAR, 'singleton').fetch(new Request(inner, request))
    }

    // Everything else → Django. (Frontend is served separately by Pages.)
    return getContainer(env.DJANGO, 'singleton').fetch(request)
  },
}
