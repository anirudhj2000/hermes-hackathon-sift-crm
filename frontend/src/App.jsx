import { useEffect, useState } from 'react'
import Landing from './Landing.jsx'
import CrmApp from './CrmApp.jsx'
import SignInPage from './SignInPage.jsx'
import { getUser, onAuthChange } from './auth.js'

function currentRoute() {
  const hash = window.location.hash
  if (hash.startsWith('#/signin')) return 'signin'
  if (hash.startsWith('#/app')) return 'app'
  return 'landing'
}

export default function App() {
  const [route, setRoute] = useState(currentRoute)
  const [user, setUser] = useState(getUser)

  useEffect(() => {
    const onHash = () => setRoute(currentRoute())
    window.addEventListener('hashchange', onHash)
    const offAuth = onAuthChange(setUser)
    return () => {
      window.removeEventListener('hashchange', onHash)
      offAuth()
    }
  }, [])

  // Signed-in users skip the sign-in page; signed-out users can't reach the app.
  if (route === 'signin') return user ? <CrmApp user={user} /> : <SignInPage />
  if (route === 'app') return user ? <CrmApp user={user} /> : <SignInPage />
  return <Landing />
}
