import { signOut } from './auth.js'

export default function AccountPage({ user }) {
  if (!user) return null
  const initial = (user.name || user.email || '?').trim().charAt(0).toUpperCase()

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Account</h1>
          <span className="page-sub">who this workspace session belongs to</span>
        </div>
      </header>

      <div className="card account-card">
        {user.picture ? (
          <img className="account-avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />
        ) : (
          <div className="account-avatar account-avatar-fallback" aria-hidden="true">
            {initial}
          </div>
        )}
        <div className="account-id">
          <div className="account-name">{user.name}</div>
          <div className="account-email">{user.email}</div>
          <span className={`account-provider ${user.provider === 'google' ? 'google' : ''}`}>
            {user.provider === 'google' ? '● GOOGLE' : '● GUEST'}
          </span>
        </div>
        <button className="account-signout" onClick={signOut}>
          SIGN OUT →
        </button>
      </div>

      <p className="flourish account-flourish">
        SESSION · STORED IN LOCALSTORAGE · API CALLS UNAUTHENTICATED (HACKATHON)
      </p>
    </div>
  )
}
