import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Alert, Field } from '../components/ui'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()

  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(identifier, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Anmeldung fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page page-narrow">
      <div className="card auth-card">
        <h1>Einloggen</h1>
        <p className="muted">Willkommen zurück.</p>

        {error && <Alert kind="error">{error}</Alert>}

        <form onSubmit={handleSubmit}>
          <Field label="Benutzername oder E-Mail">
            <input
              type="text"
              value={identifier}
              autoComplete="username"
              required
              onChange={(e) => setIdentifier(e.target.value)}
            />
          </Field>

          <Field label="Passwort">
            <input
              type="password"
              value={password}
              autoComplete="current-password"
              required
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>

          <button className="btn btn-primary btn-block btn-lg" disabled={busy}>
            {busy ? 'Einen Moment …' : 'Einloggen'}
          </button>
        </form>

        <hr className="divider" />
        <p className="small muted mb-0 center">
          Noch kein Konto? <Link to="/registrieren">Jetzt anmelden</Link>
        </p>
      </div>
    </div>
  )
}
