import { useEffect, useState } from 'react'
import Landing from './Landing.jsx'
import CrmApp from './CrmApp.jsx'

function currentRoute() {
  return window.location.hash.startsWith('#/app') ? 'app' : 'landing'
}

export default function App() {
  const [route, setRoute] = useState(currentRoute)

  useEffect(() => {
    const onHash = () => setRoute(currentRoute())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return route === 'app' ? <CrmApp /> : <Landing />
}
