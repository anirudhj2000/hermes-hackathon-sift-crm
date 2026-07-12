import { useEffect, useRef, useState } from 'react'
import { hasGoogleClientId, renderGoogleButton, signInAsGuest } from './auth.js'

export default function SignInPage() {
  const btnRef = useRef(null)
  const [gsiError, setGsiError] = useState(null)
  const googleEnabled = hasGoogleClientId()

  useEffect(() => {
    if (!googleEnabled || !btnRef.current) return
    renderGoogleButton(btnRef.current).catch((err) => setGsiError(String(err.message || err)))
  }, [googleEnabled])

  return (
    <div className="signin">
      <div className="si-card">
        <a className="si-wordmark" href="#/">
          sift<span className="si-dot" aria-hidden="true" />
        </a>
        <p className="si-eyebrow">SIGN IN</p>
        <h1 className="si-title">Open your workspace</h1>
        <p className="si-sub">
          Tables, workflows and connections stay on your machine — sign-in only names the
          session.
        </p>

        {googleEnabled ? (
          <div className="si-google" ref={btnRef} />
        ) : (
          <div className="si-fallback">
            <p className="si-note">
              VITE_GOOGLE_CLIENT_ID not set — add it to frontend/.env.local to enable Google
              sign-in.
            </p>
            <button className="si-guest" onClick={signInAsGuest}>
              CONTINUE AS GUEST →
            </button>
          </div>
        )}
        {gsiError && <p className="si-note si-err">google sign-in failed: {gsiError}</p>}

        <p className="si-meta">SESSION · LOCAL ONLY · NO DATA LEAVES :5173</p>
      </div>
    </div>
  )
}
