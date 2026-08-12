import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Alert, EmptyState, Loading, Stat } from '../components/ui'
import { sessionTypeLabel, sportIcon, sportLabel } from '../constants'
import type { Plan, Profile, Stats } from '../types'

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
}

/** Wie es um den aktiven Trainingsblock steht.
 *
 * Ein Block über wenige Tage läuft schnell aus — ohne Hinweis würde der Nutzer
 * mit einem abgelaufenen Plan dastehen, ohne dass die App etwas dazu sagt.
 */
function blockStatus(plan: Plan | null, today: string) {
  if (!plan) return null
  if (plan.end_date < today) {
    return {
      kind: 'warning' as const,
      text: `Dein Trainingsblock ist am ${formatDay(plan.end_date)} ausgelaufen.`,
      cta: 'Nächste Tage planen',
    }
  }
  if (plan.end_date === today) {
    return {
      kind: 'info' as const,
      text: 'Heute ist der letzte Tag deines Trainingsblocks.',
      cta: 'Nächste Tage planen',
    }
  }
  return null
}

/** Bewertung der Belastungsentwicklung nach dem Acute:Chronic-Verhältnis. */
function acwrVerdict(acwr: number | null): { text: string; kind: string } | null {
  if (acwr === null) return null
  if (acwr < 0.8) return { text: 'Belastung geht zurück', kind: 'badge' }
  if (acwr <= 1.3) return { text: 'Belastung im guten Bereich', kind: 'badge-success' }
  return { text: 'Belastung steigt schnell', kind: 'badge-warning' }
}

export default function Dashboard() {
  const [plan, setPlan] = useState<Plan | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([api.activePlan(), api.stats(), api.getProfile()])
      .then(([activePlan, loadedStats, loadedProfile]) => {
        setPlan(activePlan)
        setStats(loadedStats)
        setProfile(loadedProfile)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Loading />
  if (error) return <Alert kind="error">{error}</Alert>

  const today = todayIso()
  const todaySessions = plan?.sessions.filter((s) => s.date === today) ?? []
  const upcoming =
    plan?.sessions
      .filter((s) => s.date > today && s.sport !== 'rest')
      .slice(0, 5) ?? []

  const currentWeek = stats?.weekly.at(-1)
  const verdict = acwrVerdict(stats?.acwr ?? null)
  const block = blockStatus(plan, today)
  const missingCoreValues =
    profile && (!profile.max_hr || !profile.resting_hr || !profile.birth_date)

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Übersicht</h1>
          <p>
            {new Date().toLocaleDateString('de-DE', {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}
          </p>
        </div>
        <div className="row">
          {plan?.is_active && (() => {
            const nextStart = new Date(plan.end_date)
            nextStart.setDate(nextStart.getDate() + 1)
            const nextStartStr = nextStart.toISOString().slice(0, 10)
            return (
              <Link className="btn btn-secondary" to={`/plan-erzeugen?start=${nextStartStr}&days=7`}>
                Nächste 7 Tage planen
              </Link>
            )
          })()}
          <Link className="btn btn-secondary" to="/training-erfassen">
            Training erfassen
          </Link>
          <Link className="btn btn-primary" to="/neues-training">
            Neues Training
          </Link>
        </div>
      </div>

      {block && (
        <Alert kind={block.kind}>
          {block.text} Die letzten vier Wochen fließen automatisch mit ein.{' '}
          <Link to="/plan-erzeugen">{block.cta}</Link>
        </Alert>
      )}

      {missingCoreValues && (
        <Alert kind="warning">
          Für präzise Herzfrequenzzonen fehlen noch Angaben (Geburtsdatum, Ruhepuls oder
          Maximalpuls). <Link to="/profil">Jetzt ergänzen</Link>
        </Alert>
      )}

      <div className="grid grid-4 mb-1">
        <Stat
          label="Diese Woche"
          value={currentWeek?.sessions ?? 0}
          unit="Einheiten"
          hint={currentWeek ? `${currentWeek.total_minutes} min gesamt` : undefined}
        />
        <Stat
          label="Distanz diese Woche"
          value={currentWeek?.total_km ?? 0}
          unit="km"
        />
        <Stat
          label="4-Wochen-Umfang"
          value={stats ? Math.round(stats.total_minutes / 60) : 0}
          unit="Stunden"
          hint={stats ? `${stats.total_sessions} Einheiten` : undefined}
        />
        <Stat
          label="Belastungsverhältnis"
          value={stats?.acwr ?? '–'}
          hint={
            verdict ? (
              <span className={`badge ${verdict.kind}`}>{verdict.text}</span>
            ) : (
              'Braucht zwei Wochen mit RPE-Angaben'
            )
          }
        />
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="card-title">
            <h2>Heute</h2>
            {plan && <Link className="small" to="/plan">Ganzen Plan ansehen</Link>}
          </div>

          {!plan ? (
            <EmptyState icon="📋" title="Kein aktiver Plan">
              <p className="small">
                Beantworte den Fragebogen und lass dir einen Plan erzeugen. Oder sieh dir
                deine früheren Pläne an.
              </p>
              <Link className="btn btn-secondary" to="/plan">
                Frühere Pläne ansehen
              </Link>
              <Link className="btn btn-primary" to="/neues-training">
                Neues Training starten
              </Link>
            </EmptyState>
          ) : todaySessions.length === 0 ? (
            <p className="muted mb-0">
              {plan.end_date < today
                ? `Der Block lief vom ${formatDay(plan.start_date)} bis ${formatDay(
                    plan.end_date,
                  )} und ist abgeschlossen.`
                : `Für heute ist nichts vorgesehen. Der Block läuft vom ${formatDay(
                    plan.start_date,
                  )} bis ${formatDay(plan.end_date)}.`}
            </p>
          ) : (
            <div className="session-list">
              {todaySessions.map((session) => (
                <div
                  className={`session-card ${session.sport === 'rest' ? 'is-rest' : ''} ${
                    session.logged ? 'is-logged' : ''
                  }`}
                  key={session.id}
                >
                  <span className="session-icon">{sportIcon(session.sport)}</span>
                  <span className="session-body">
                    <span className="session-head">
                      <span className="session-title">{session.title}</span>
                      {session.logged && (
                        <span className="badge badge-success">✓ erfasst</span>
                      )}
                    </span>
                    <span className="session-meta">
                      <span>{sportLabel(session.sport)}</span>
                      <span>{sessionTypeLabel(session.session_type)}</span>
                      {session.duration_min ? <span>{session.duration_min} min</span> : null}
                      {session.target_hr_low && session.target_hr_high ? (
                        <span>
                          {session.target_hr_low}–{session.target_hr_high} bpm
                        </span>
                      ) : null}
                    </span>
                    {session.structure && (
                      <span className="session-structure">{session.structure}</span>
                    )}
                  </span>
                </div>
              ))}

              {todaySessions.some((s) => !s.logged && s.sport !== 'rest') && (
                <Link className="btn btn-primary mt-1" to="/training-erfassen">
                  Training erfassen
                </Link>
              )}
            </div>
          )}
        </div>

        <div className="card">
          <h2>Als Nächstes</h2>
          {upcoming.length === 0 ? (
            <p className="muted mb-0">Keine weiteren Einheiten geplant.</p>
          ) : (
            <div className="table-wrap">
              <table className="table-cards">
                <tbody>
                  {upcoming.map((session) => (
                    <tr key={session.id}>
                      <td className="nowrap muted small" data-label="Tag">
                        {new Date(session.date).toLocaleDateString('de-DE', {
                          weekday: 'short',
                          day: '2-digit',
                          month: '2-digit',
                        })}
                      </td>
                      <td className="cell-title">
                        {sportIcon(session.sport)} {session.title}
                      </td>
                      <td
                        className="nowrap muted small"
                        data-label={session.duration_min ? 'Dauer' : undefined}
                      >
                        {session.duration_min ? `${session.duration_min} min` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {stats?.compliance && stats.compliance.rate_pct !== null && (
            <>
              <hr className="divider" />
              <h3>Umsetzung</h3>
              <p className="small muted mb-0">
                {stats.compliance.logged} von {stats.compliance.planned_past} fälligen
                Einheiten erfasst ({stats.compliance.rate_pct} %).
              </p>
            </>
          )}
        </div>
      </div>

      {stats && stats.weekly.some((w) => w.sessions > 0) && (
        <div className="card">
          <h2>Die letzten vier Wochen</h2>
          <div className="table-wrap">
            <table className="table-cards">
              <thead>
                <tr>
                  <th>Woche ab</th>
                  <th>Einheiten</th>
                  <th>Minuten</th>
                  <th>Kilometer</th>
                  <th>Ø RPE</th>
                  <th>Last (sRPE)</th>
                </tr>
              </thead>
              <tbody>
                {stats.weekly.map((week) => (
                  <tr key={week.week_start}>
                    <td className="nowrap cell-title" data-label="Woche ab">
                      {new Date(week.week_start).toLocaleDateString('de-DE', {
                        day: '2-digit',
                        month: '2-digit',
                      })}
                    </td>
                    <td data-label="Einheiten">{week.sessions}</td>
                    <td data-label="Minuten">{week.total_minutes}</td>
                    <td data-label="Kilometer">{week.total_km}</td>
                    <td data-label="Ø RPE">{week.avg_rpe ?? '–'}</td>
                    <td data-label="Last">{week.total_srpe_load ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}
