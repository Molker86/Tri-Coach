import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Alert, Field } from '../components/ui'

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await register(email, username)
      // Direkt ins Profil: ohne Leistungswerte kann die KI wenig anfangen.
      navigate('/profil')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registrierung fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page page-narrow">
      <div className="card auth-card">
        <h1>Anmelden</h1>
        <p className="muted">Ein Konto, danach geht es direkt zu deinen Daten.</p>

        {error && <Alert kind="error">{error}</Alert>}

        <form onSubmit={handleSubmit}>
          <Field label="E-Mail">
            <input
              type="email"
              value={email}
              autoComplete="email"
              required
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>

          <Field
            label="Benutzername"
            hint="Unter diesem Namen erscheint das Konto in der Anmeldeliste."
          >
            <input
              type="text"
              value={username}
              autoComplete="username"
              required
              minLength={3}
              onChange={(e) => setUsername(e.target.value)}
            />
          </Field>

          <button className="btn btn-primary btn-block btn-lg" disabled={busy}>
            {busy ? 'Konto wird angelegt …' : 'Konto anlegen'}
          </button>
        </form>

        <hr className="divider" />
        <p className="small muted mb-0 center">
          Schon registriert? <Link to="/login">Einloggen</Link>
        </p>
      </div>
    </div>
  )
}
