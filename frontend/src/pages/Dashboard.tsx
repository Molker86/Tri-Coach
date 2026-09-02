import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { AnpassungsKarte } from '../components/AnpassungsKarte'
import { SessionCard } from '../components/SessionCard'
import { SessionDetail } from '../components/SessionDetail'
import { Alert, EmptyState, Loading, Stat } from '../components/ui'
import { useEinheitAnpassung } from '../components/useEinheitAnpassung'
import { schlafdauer, sportIcon, sportLabel } from '../constants'
import { heuteIso, istHeute, naechsterBlockStart, planErzeugenPfad } from '../planung'
import type {
  GarminAccount,
  Plan,
  PlanSession,
  Profile,
  Stats,
  WeeklyBucket,
  WellnessDay,
} from '../types'

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
}

/** Von wann die Zahlen auf dieser Seite sind.
 *
 * Hier stand einmal das heutige Datum — über Erholungswerten, die bis zum
 * Abgleich des Tages noch von gestern stammen. Das Datum behauptete damit eine
 * Frische, die die Daten darunter nicht hatten; der Zeitpunkt des letzten
 * Abgleichs sagt stattdessen, worauf man gerade sieht. Ohne Abgleich bleibt es
 * beim heutigen Datum: Dann kommt auf dieser Seite nichts aus der Uhr.
 */
function datenstand(letzterAbgleich: string | null): string {
  if (!letzterAbgleich) {
    return new Date().toLocaleDateString('de-DE', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
    })
  }
  const zeitpunkt = new Date(letzterAbgleich)
  const uhrzeit = zeitpunkt.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })
  if (zeitpunkt.toDateString() === new Date().toDateString()) {
    return `Garmin-Daten von heute, ${uhrzeit} Uhr`
  }
  const tag = zeitpunkt.toLocaleDateString('de-DE', { dateStyle: 'short' })
  return `Garmin-Daten vom ${tag}, ${uhrzeit} Uhr`
}

/** Immer diese drei, immer in dieser Reihenfolge.
 *
 * Erst hingen die Zeilen daran, ob überhaupt Kilometer zusammenkamen — eine
 * Woche aus Indoor-Rad, Kraft und Mobility hatte deshalb gar nichts zum
 * Aufklappen, und die Kachel ließ sich nicht anklicken. Genau dann ist die
 * Aufschlüsselung aber die Antwort auf die Frage, die man stellt: *welche*
 * Disziplin steht auf null. Die drei stehen also fest, auch mit 0,0 km, und
 * fest in der Triathlonreihenfolge — nach Umfang sortiert sprängen die Zeilen
 * von Woche zu Woche.
 */
const DISTANZ_DISZIPLINEN = ['swim', 'bike', 'run']

/** Die Wochenkilometer je Sportart: die drei Disziplinen und, was sonst noch
 *  Strecke hatte (Koppeltraining). Kraft und Mobility fahren nie welche und
 *  wären als Dauer-Nullzeile nur Rauschen. */
function distanzNachSport(woche: WeeklyBucket | undefined) {
  const bySport = woche?.by_sport ?? {}
  const weitere = Object.entries(bySport)
    .filter(([sport, wert]) => wert.km > 0 && !DISTANZ_DISZIPLINEN.includes(sport))
    .map(([sport, wert]) => ({ sport, km: wert.km }))
    .sort((a, b) => b.km - a.km)
  return [
    ...DISTANZ_DISZIPLINEN.map((sport) => ({ sport, km: bySport[sport]?.km ?? 0 })),
    ...weitere,
  ]
}

/** Wochenkilometer, aufklappbar nach Sportart.
 *
 * Die Summe allein sagt wenig: 25 km sind auf dem Rad eine kurze Ausfahrt und
 * im Wasser eine Woche, die es nie gab. Die Aufschlüsselung hängt deshalb an
 * der Kachel selbst statt in einer eigenen Tabelle. Anklickbar ist die **ganze
 * Kachel** — dort greift die Hand hin, nicht auf eine Textzeile darunter —,
 * aber als echter `<button>` und nicht als `div` mit `onClick`, sonst wäre sie
 * für Tastatur und Vorlesehilfe kein Bedienelement. Innen deshalb nur `span`:
 * Ein `div` im Knopf ist kein gültiges HTML.
 */
function DistanzKachel({ woche }: { woche: WeeklyBucket | undefined }) {
  const [offen, setOffen] = useState(false)
  const nachSport = distanzNachSport(woche)

  return (
    <div className="stat">
      <button
        type="button"
        className="stat-toggle"
        aria-expanded={offen}
        onClick={() => setOffen((wert) => !wert)}
      >
        <span className="stat-label">Distanz diese Woche</span>
        <span className="stat-value">
          {woche?.total_km ?? 0}
          <span className="stat-unit">km</span>
        </span>
        <span className="stat-hint">
          {offen ? 'Aufschlüsselung ausblenden' : 'Nach Sportart aufschlüsseln'}
        </span>
      </button>
      {offen && (
        <ul className="stat-split">
          {nachSport.map((eintrag) => (
            <li key={eintrag.sport}>
              <span>
                {sportIcon(eintrag.sport)} {sportLabel(eintrag.sport)}
              </span>
              <span>{eintrag.km.toFixed(1)} km</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
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

/** Jüngster belegter Wert einer Größe aus den Fitnessdaten.
 *
 * Nicht einfach der Wert von heute: Garmin trägt Schlaf und Erholungswerte
 * teils erst im Laufe des Vormittags nach, und ein Gewicht wird nicht täglich
 * gemessen. Ohne diesen Rückgriff stünden die Kacheln morgens leer da.
 */
function letzterWert<K extends keyof WellnessDay>(
  tage: WellnessDay[],
  feld: K,
): WellnessDay[K] | null {
  for (const tag of tage) {
    if (tag[feld] !== null && tag[feld] !== undefined) return tag[feld]
  }
  return null
}

/** Einordnung der Trainingsreife in eine Ampel. */
function reifeBewertung(score: number | null): string {
  if (score === null) return 'badge'
  if (score < 40) return 'badge-warning'
  if (score < 65) return 'badge'
  return 'badge-success'
}

const HRV_STATUS_TEXT: Record<string, string> = {
  BALANCED: 'im Normalbereich',
  UNBALANCED: 'außerhalb der Norm',
  LOW: 'niedrig',
  POOR: 'deutlich niedrig',
  NOT_ENOUGH_DATA: 'zu wenig Daten',
}

/** Bewertung der Belastungsentwicklung nach dem Acute:Chronic-Verhältnis. */
function acwrVerdict(acwr: number | null): { text: string; kind: string } | null {
  if (acwr === null) return null
  if (acwr < 0.8) return { text: 'Belastung geht zurück', kind: 'badge' }
  if (acwr <= 1.3) return { text: 'Belastung im guten Bereich', kind: 'badge-success' }
  return { text: 'Belastung steigt schnell', kind: 'badge-warning' }
}

/** Was Garmin über die Erholung sagt.
 *
 * Steht bewusst weit oben: Hier wird morgens die Frage gestellt „kann ich heute
 * hart trainieren?" — und genau darauf antworten diese vier Werte.
 */
function ErholungsKacheln({ tage }: { tage: WellnessDay[] }) {
  const reife = letzterWert(tage, 'readiness_score')
  const hrv = letzterWert(tage, 'hrv_last_night_ms')
  const hrvStatus = letzterWert(tage, 'hrv_status')
  const schlafSekunden = letzterWert(tage, 'sleep_seconds')
  const schlafScore = letzterWert(tage, 'sleep_score')
  const ruhepuls = letzterWert(tage, 'resting_hr')
  // Garmin liefert Minuten; die Kachel zeigt Stunden.
  const erholungMinuten = letzterWert(tage, 'recovery_time_min')
  const erholungszeit =
    erholungMinuten === null ? null : Math.round((erholungMinuten / 60) * 10) / 10

  // Der Ruhepuls sagt erst im Vergleich etwas. Die vier Wochen dienen als
  // eigene Grundlinie — ein Anstieg darüber ist ein Warnzeichen.
  const alleRuhepulse = tage.map((t) => t.resting_hr).filter((w): w is number => w !== null)
  const schnitt =
    alleRuhepulse.length > 0
      ? Math.round(alleRuhepulse.reduce((a, b) => a + b, 0) / alleRuhepulse.length)
      : null
  const abweichung = ruhepuls !== null && schnitt !== null ? ruhepuls - schnitt : null

  return (
    <div className="grid grid-4 mb-1">
      <Stat
        label="Trainingsreife"
        value={reife ?? '–'}
        hint={
          reife !== null ? (
            <span className={`badge ${reifeBewertung(reife)}`}>
              {reife < 40 ? 'Heute locker' : reife < 65 ? 'Kein Schlüsseltraining' : 'Bereit'}
            </span>
          ) : (
            'Von Garmin'
          )
        }
      />
      <Stat
        label="HRV letzte Nacht"
        value={hrv !== null ? Math.round(hrv) : '–'}
        unit="ms"
        hint={hrvStatus ? (HRV_STATUS_TEXT[hrvStatus] ?? hrvStatus) : undefined}
      />
      <Stat
        label="Schlaf letzte Nacht"
        value={schlafSekunden !== null ? schlafdauer(schlafSekunden) : '–'}
        hint={schlafScore !== null ? `Schlafscore ${schlafScore}` : undefined}
      />
      <Stat
        label="Ruhepuls"
        value={ruhepuls ?? '–'}
        unit="bpm"
        hint={
          abweichung !== null && abweichung !== 0
            ? `${abweichung > 0 ? '+' : ''}${abweichung} gegenüber dem Schnitt`
            : erholungszeit
              ? `Noch ${erholungszeit} h Erholung`
              : undefined
        }
      />
    </div>
  )
}

export default function Dashboard() {
  const [plan, setPlan] = useState<Plan | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [wellness, setWellness] = useState<WellnessDay[]>([])
  const [garminKonto, setGarminKonto] = useState<GarminAccount | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<PlanSession | null>(null)

  // Als eigene Funktion und nicht nur im Effekt: Nach einer angepassten Einheit
  // steht eine andere Vorgabe im Plan, und die Übersicht zeigte sonst bis zum
  // Neuladen der Seite die alte.
  const reload = useCallback(() => {
    Promise.all([
      api.activePlan(),
      api.stats(),
      api.getProfile(),
      // Ohne verbundenes Garmin-Konto ist die Liste leer — das ist kein Fehler,
      // und die Übersicht darf daran nicht scheitern.
      api.garminWellness(4).catch(() => [] as WellnessDay[]),
      // Nur wegen des Datenstands in der Kopfzeile. Die Anfrage kostet nichts
      // gegen Garmin — sie liest den Stand aus der eigenen Datenbank.
      api.garminStatus().then((zustand) => zustand.konto).catch(() => null),
    ])
      .then(([activePlan, loadedStats, loadedProfile, loadedWellness, konto]) => {
        setPlan(activePlan)
        setStats(loadedStats)
        setProfile(loadedProfile)
        setWellness(loadedWellness)
        setGarminKonto(konto)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => reload(), [reload])

  // Dieselbe Anpassung wie im Trainingsplan — der Hook trägt Abfrageschleife
  // und Fortschritt, damit beide Seiten nicht zwei Fassungen davon haben.
  const anpassungLauf = useEinheitAnpassung(reload, setError)
  const anpassung = anpassungLauf.anpassung

  if (loading) return <Loading />
  if (error) return <Alert kind="error">{error}</Alert>

  const today = heuteIso()
  const todaySessions = plan?.sessions.filter((s) => s.date === today) ?? []
  // Was die Tagesanpassung heute früh geändert hat. Erkennbar am **fehlenden**
  // Wunsch: Wer selbst angepasst hat, weiß es ohnehin und braucht den Hinweis
  // nicht. Die Begründung gilt für den ganzen Tag und steht an jeder
  // angefassten Einheit gleich — also einmal, nicht je Karte.
  const tagesanpassung = todaySessions.find(
    (s) => s.anpassungswunsch == null && istHeute(s.angepasst_am),
  )
  const upcoming =
    plan?.sessions
      .filter((s) => s.date > today && s.sport !== 'rest')
      .slice(0, 5) ?? []

  const currentWeek = stats?.weekly.at(-1)
  const verdict = acwrVerdict(stats?.acwr ?? null)
  const block = blockStatus(plan, today)
  const missingCoreValues =
    profile && (!profile.max_hr || !profile.resting_hr || !profile.birth_date)
  const garminProblem = garminKonto != null && garminKonto.status !== 'connected'

  return (
    <>
      {/* Außerhalb des Dialogs, wie im Trainingsplan: Der Lauf dauert Minuten,
          und wer den Dialog zwischendurch schließt, verlöre sonst sowohl den
          Fortschritt als auch die Begründung der KI. */}
      {anpassung && (
        <AnpassungsKarte
          job={anpassung}
          onAbbrechen={anpassungLauf.abbrechen}
          onSchliessen={anpassungLauf.vergiss}
        />
      )}

      {selected && (
        <SessionDetail
          session={selected}
          kiVerfuegbar={anpassungLauf.kiVerfuegbar}
          anpassungLaeuft={anpassungLauf.laeuft}
          onLauf={(job) => {
            anpassungLauf.beobachte(job)
            setSelected(null)
          }}
          onUebernommen={() => {
            setSelected(null)
            reload()
          }}
          onClose={() => setSelected(null)}
        />
      )}

      <div className="page-header">
        <div>
          <h1>Übersicht</h1>
          <p>{datenstand(garminKonto?.last_sync_at ?? null)}</p>
        </div>
        <div className="row">
          {/* Nur einer von beiden: Läuft der Block noch, ist die Frage „soll
              der Rest so bleiben?" — ist er vorbei, gibt es nichts zu ersetzen.
              Beide Wege nebeneinander stünden am Telefon in der dritten Zeile. */}
          {plan?.is_active && (
            <Link
              className="btn btn-secondary"
              to={planErzeugenPfad(
                plan.end_date >= today ? today : naechsterBlockStart(plan.end_date),
              )}
            >
              {plan.end_date >= today ? 'Neu planen ab heute' : 'Nächsten Block planen'}
            </Link>
          )}
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

      {/* Ein stehengebliebener Abgleich sieht auf dieser Seite aus wie eine
          Woche ohne Training: Alle Zahlen stehen auf null, und der Datenstand
          in der Kopfzeile ist die einzige, leicht zu übersehende Erklärung.
          Deshalb hier ausdrücklich — es ist der einzige Grund, aus dem die
          Kacheln lügen können. */}
      {garminProblem && (
        <Alert kind="warning">
          {garminKonto?.status_message ?? 'Der Garmin-Abgleich hat ein Problem.'} Bis dahin
          fehlen alle Trainings und Werte seit dem letzten Abgleich.{' '}
          <Link to="/garmin">Verbindung prüfen</Link>
        </Alert>
      )}

      <div className="grid grid-4 mb-1">
        <Stat
          label="Diese Woche"
          value={currentWeek?.sessions ?? 0}
          unit="Einheiten"
          hint={currentWeek ? `${currentWeek.total_minutes} min gesamt` : undefined}
        />
        <DistanzKachel woche={currentWeek} />
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

      {wellness.length > 0 && <ErholungsKacheln tage={wellness} />}

      <div className="card">
        <div className="card-title">
          <h2>Heute</h2>
          {plan && <Link className="small" to="/plan">Ganzen Plan ansehen</Link>}
        </div>

        {/* Ausrichtung und Steuerungshinweise standen bisher nur im
            Trainingsplan — dabei gehören sie über die Einheit von heute: Sie
            sagen, warum der Block so liegt und woran zu steuern ist, und
            werden gelesen, bevor der Athlet auf die Vorgabe des Tages sieht.
            Wer den Block automatisch erzeugen lässt, sieht die Planansicht
            sonst nie. */}
        {plan && (plan.summary || plan.coaching_notes) && (
          <>
            {plan.summary && (
              <>
                <h3>Zur Ausrichtung des Blocks</h3>
                <p className={plan.coaching_notes ? '' : 'mb-0'}>{plan.summary}</p>
              </>
            )}
            {plan.coaching_notes && (
              <>
                <h3>Hinweise zur Steuerung</h3>
                <p className="mb-0">{plan.coaching_notes}</p>
              </>
            )}
            <hr className="divider" />
          </>
        )}

        {/* Über den Einheiten und nicht nur als Fähnchen an der Karte: Die
            Anpassung ist nachts passiert, und wer die App morgens öffnet, soll
            nicht erst eine Einheit anklicken müssen, um zu erfahren, dass und
            warum sein Tag anders aussieht als gestern Abend geplant. */}
        {tagesanpassung && (
          <Alert kind="info">
            <strong>✎ Heute früh an deine Tagesform angepasst.</strong>
            {tagesanpassung.anpassungsbegruendung && (
              <> {tagesanpassung.anpassungsbegruendung}</>
            )}
          </Alert>
        )}

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
          /* Dieselbe Karte wie im Trainingsplan, nicht mehr eine nachgebaute:
             Sie war hier ein toter `<div>` ohne Zone, Garmin-Marke und
             „angepasst" — und ohne Weg zum Dialog. Wer eine Einheit ansehen
             oder umschreiben lassen wollte, musste erst die Seite wechseln. */
          <div className="session-list">
            {todaySessions.map((session) => (
              <SessionCard
                key={session.id}
                session={session}
                onOpen={() => setSelected(session)}
              />
            ))}

            {/* Kein Knopf zum Erfassen mehr: Die Einheit gilt als absolviert,
                sobald sie der Garmin-Abgleich als Aktivität hereinholt. */}
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
                      {/* Ein Knopf und nicht die ganze Zeile mit `onClick`:
                          Eine anklickbare Zeile ist für Tastatur und
                          Vorlesehilfe kein Bedienelement. */}
                      <button
                        className="linklike"
                        onClick={() => setSelected(session)}
                      >
                        {sportIcon(session.sport)} {session.title}
                      </button>
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
