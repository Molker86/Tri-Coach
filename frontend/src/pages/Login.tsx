import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, getLastUserId } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Alert, Field, Loading } from '../components/ui'
import type { UserOption } from '../types'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()

  const [users, setUsers] = useState<UserOption[] | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .listUsers()
      .then((list) => {
        if (cancelled) return
        setUsers(list)
        // Zuletzt genutztes Konto vorauswählen; ist es weg, das erste der Liste.
        const last = getLastUserId()
        setSelected(list.find((u) => u.id === last)?.id ?? list[0]?.id ?? null)
      })
      .catch((err) => {
        if (cancelled) return
        setUsers([])
        setError(
          err instanceof Error ? err.message : 'Die Konten konnten nicht geladen werden.',
        )
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (selected === null) return
    setError(null)
    setBusy(true)
    try {
      await login(selected)
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

        {users === null ? (
          <Loading text="Konten werden geladen …" />
        ) : users.length === 0 ? (
          <p className="muted">Es gibt noch kein Konto.</p>
        ) : (
          <form onSubmit={handleSubmit}>
            <Field label="Konto">
              <select
                value={selected ?? ''}
                onChange={(e) => setSelected(Number(e.target.value))}
              >
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.username}
                  </option>
                ))}
              </select>
            </Field>

            <button
              className="btn btn-primary btn-block btn-lg"
              disabled={busy || selected === null}
            >
              {busy ? 'Einen Moment …' : 'Einloggen'}
            </button>
          </form>
        )}

        <hr className="divider" />
        <p className="small muted mb-0 center">
          Noch kein Konto? <Link to="/registrieren">Jetzt anmelden</Link>
        </p>
      </div>
    </div>
  )
}
