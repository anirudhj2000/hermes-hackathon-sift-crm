// Client-side Google sign-in via Google Identity Services (GIS).
// No backend involvement: the GIS credential (a signed JWT) is decoded in the
// browser for display identity only — API calls stay unauthenticated.
// Set VITE_GOOGLE_CLIENT_ID in frontend/.env.local to enable the real button;
// without it the sign-in page offers a local guest session instead.

const STORAGE_KEY = 'sift.user'
const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? ''

const listeners = new Set()

export function getUser() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function setUser(user) {
  if (user) localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
  else localStorage.removeItem(STORAGE_KEY)
  listeners.forEach((fn) => fn(user))
}

export function onAuthChange(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function hasGoogleClientId() {
  return Boolean(CLIENT_ID)
}

function decodeJwtPayload(token) {
  const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
  const json = decodeURIComponent(
    atob(b64)
      .split('')
      .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
      .join('')
  )
  return JSON.parse(json)
}

let gsiPromise = null
function loadGsi() {
  if (!gsiPromise) {
    gsiPromise = new Promise((resolve, reject) => {
      if (window.google?.accounts?.id) return resolve(window.google.accounts.id)
      const s = document.createElement('script')
      s.src = 'https://accounts.google.com/gsi/client'
      s.async = true
      s.onload = () => resolve(window.google.accounts.id)
      s.onerror = () => reject(new Error('failed to load google identity services'))
      document.head.appendChild(s)
    })
  }
  return gsiPromise
}

// Renders Google's official button into `el`. Sign-in completes through the
// callback, which stores the user and notifies onAuthChange subscribers.
export async function renderGoogleButton(el) {
  const gsi = await loadGsi()
  gsi.initialize({
    client_id: CLIENT_ID,
    callback: (res) => {
      const p = decodeJwtPayload(res.credential)
      setUser({
        name: p.name,
        email: p.email,
        picture: p.picture || null,
        sub: p.sub,
        provider: 'google',
      })
    },
  })
  gsi.renderButton(el, {
    theme: 'filled_black',
    size: 'large',
    shape: 'pill',
    text: 'continue_with',
    width: 280,
  })
}

export function signInAsGuest() {
  setUser({ name: 'Guest', email: 'guest@sift.local', picture: null, provider: 'guest' })
}

export function signOut() {
  try {
    window.google?.accounts?.id?.disableAutoSelect()
  } catch {
    /* gsi not loaded — nothing to reset */
  }
  setUser(null)
}
