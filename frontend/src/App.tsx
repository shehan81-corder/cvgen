import { useEffect, useState } from 'react'
import './App.css'

type HealthStatus = 'checking' | 'ok' | 'error'

function App() {
  const [status, setStatus] = useState<HealthStatus>('checking')

  useEffect(() => {
    fetch('/api/health')
      .then((res) => {
        if (!res.ok) throw new Error(`status ${res.status}`)
        return res.json()
      })
      .then(() => setStatus('ok'))
      .catch(() => setStatus('error'))
  }, [])

  return (
    <main>
      <h1>CVGen</h1>
      <p>
        Backend status:{' '}
        {status === 'checking' && 'checking...'}
        {status === 'ok' && 'connected'}
        {status === 'error' && 'unreachable'}
      </p>
    </main>
  )
}

export default App
