/**
 * Fortschritt und Ergebnis einer Einzelanpassung, außerhalb des Dialogs.
 *
 * Aus `PlanView` herausgezogen: Das Dashboard bietet dieselbe Anpassung an und
 * braucht dieselbe Karte. Zwei Kopien liefen beim nächsten Zustand des Laufs
 * auseinander.
 */

import { jobLaeuft } from '../api/client'
import { Alert } from './ui'
import type { KiJob } from '../types'

/** Fortschritt und Ergebnis einer Einzelanpassung.
 *
 * Bleibt nach dem Lauf stehen, bis der Nutzer sie wegklickt: Die Begründung der
 * KI ist die einzige Stelle, an der er erfährt, ob sie seinem Wunsch gefolgt
 * ist — und ob sie ihm aus trainingswissenschaftlichen Gründen widersprochen
 * hat. Sie beim Neuladen wegzuwerfen hieße, genau das zu verschlucken.
 */
export function AnpassungsKarte({
  job,
  onAbbrechen,
  onSchliessen,
}: {
  job: KiJob
  onAbbrechen: () => void
  onSchliessen: () => void
}) {
  const laeuft = jobLaeuft(job)
  const geglueckt = job.state === 'done'

  if (laeuft) {
    return (
      <div className="card">
        <h3>Die Einheit wird angepasst …</h3>
        <div className="wizard-progress">
          <div
            className="wizard-step-bar current"
            style={{ flexGrow: Math.max(1, job.progress_pct) }}
          />
          <div
            className="wizard-step-bar"
            style={{ flexGrow: Math.max(1, 100 - job.progress_pct) }}
          />
        </div>
        <p className="muted mb-0">{job.message ?? 'Der Lauf wird vorbereitet …'}</p>
        <div className="row mt-1">
          <span className="small faint">
            {job.wunsch ? `Dein Wunsch: „${job.wunsch}“ · ` : ''}
            {job.progress_pct}&nbsp;% — du kannst die Seite verlassen, der Lauf geht im
            Hintergrund weiter.
          </span>
          <button className="btn btn-ghost btn-sm" onClick={onAbbrechen}>
            Abbrechen
          </button>
        </div>
      </div>
    )
  }

  return (
    <Alert kind={geglueckt ? 'success' : 'warning'}>
      {job.message ?? (geglueckt ? 'Die Einheit wurde angepasst.' : 'Der Lauf endete.')}
      <div className="row row-end mt-1">
        <button className="btn btn-ghost btn-sm" onClick={onSchliessen}>
          Verstanden
        </button>
      </div>
    </Alert>
  )
}
