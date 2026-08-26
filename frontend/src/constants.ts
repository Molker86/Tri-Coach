import type { Discipline, Sport, Weekday } from './types'

export const WEEKDAYS: { key: Weekday; label: string; short: string }[] = [
  { key: 'monday', label: 'Montag', short: 'Mo' },
  { key: 'tuesday', label: 'Dienstag', short: 'Di' },
  { key: 'wednesday', label: 'Mittwoch', short: 'Mi' },
  { key: 'thursday', label: 'Donnerstag', short: 'Do' },
  { key: 'friday', label: 'Freitag', short: 'Fr' },
  { key: 'saturday', label: 'Samstag', short: 'Sa' },
  { key: 'sunday', label: 'Sonntag', short: 'So' },
]

export const DISCIPLINES: {
  key: Discipline
  label: string
  icon: string
  description: string
}[] = [
  {
    key: 'run',
    label: 'Laufen',
    icon: '🏃',
    description: 'Von 5 km bis Marathon — reines Lauftraining.',
  },
  {
    key: 'bike',
    label: 'Radfahren',
    icon: '🚴',
    description: 'Straße, Rolle oder Gravel — Ausdauer und Watt.',
  },
  {
    key: 'swim',
    label: 'Schwimmen',
    icon: '🏊',
    description: 'Technik, Intervalle und Streckenschwimmen.',
  },
  {
    key: 'triathlon',
    label: 'Triathlon',
    icon: '🏅',
    description: 'Alle drei Disziplinen kombiniert, inklusive Koppeltraining.',
  },
]

export const SPORT_LABEL: Record<Sport, string> = {
  run: 'Laufen',
  bike: 'Radfahren',
  swim: 'Schwimmen',
  strength: 'Kraft',
  mobility: 'Beweglichkeit',
  brick: 'Koppeltraining',
  rest: 'Ruhetag',
}

export const SPORT_ICON: Record<Sport, string> = {
  run: '🏃',
  bike: '🚴',
  swim: '🏊',
  strength: '🏋️',
  mobility: '🧘',
  brick: '🔁',
  rest: '😴',
}

/**
 * Welche Ausdauersportarten eine Disziplin umfasst — Gegenstück zu
 * `DISZIPLIN_SPORTARTEN` in `backend/app/schemas.py`. Kraft, Mobility und Ruhe
 * stehen bewusst nicht darin: Sie hängen am Ergänzungswunsch, nicht an der
 * Disziplin.
 */
export const DISCIPLINE_SPORTS: Record<Discipline, Sport[]> = {
  run: ['run'],
  bike: ['bike'],
  swim: ['swim'],
  triathlon: ['swim', 'bike', 'run'],
}

export const SESSION_TYPE_LABEL: Record<string, string> = {
  recovery: 'Regeneration',
  easy: 'Locker',
  endurance: 'Grundlagenausdauer',
  tempo: 'Tempo',
  threshold: 'Schwelle',
  vo2max: 'VO2max',
  intervals: 'Intervalle',
  long: 'Lange Einheit',
  technique: 'Technik',
  race_pace: 'Wettkampftempo',
  strength: 'Kraft',
  mobility: 'Beweglichkeit',
  brick: 'Koppeltraining',
  test: 'Leistungstest',
  rest: 'Ruhe',
}

// Die Schlüssel gehen unverändert als `trainingswunsch.ziel` in den Export und
// werden im Prompt namentlich angesprochen (Punkt 6 der Trainingsprinzipien in
// `ai_export.py`): Er unterscheidet Ziele, die einen Reiz verlangen, von
// solchen, bei denen Regelmäßigkeit mehr zählt. Wer hier einen Schlüssel
// ändert oder ergänzt, muss den Prompt mitziehen.
export const GOAL_OPTIONS = [
  {
    key: 'Standardplan',
    label: 'Standardplan — bestmögliche Entwicklung',
    hint: 'Kein festes Ziel: Aus deinen letzten Wochen wird abgeleitet, was jetzt am meisten bringt — nach den Best-Practice-Methoden des Ausdauersports.',
  },
  {
    key: 'Wettkampfvorbereitung',
    label: 'Wettkampf vorbereiten',
    hint: 'Auf ein festes Datum hin — Form zum Wettkampf.',
  },
  {
    key: 'Bestzeit',
    label: 'Persönliche Bestzeit verbessern',
    hint: 'Bekannte Distanz, schneller als bisher.',
  },
  {
    key: 'Aufbau',
    label: 'Allgemeines Aufbautraining',
    hint: 'Ohne Wettkampf leistungsfähiger werden — mit Schwellen- und VO2max-Reizen.',
  },
  {
    key: 'Grundlagenausdauer',
    label: 'Grundlagenausdauer aufbauen',
    hint: 'Umfang im lockeren Bereich, wenig Intensität.',
  },
  {
    key: 'Wiedereinstieg',
    label: 'Wiedereinstieg nach Pause oder Verletzung',
    hint: 'Vorsichtig herantasten, Belastung langsam steigern.',
  },
  {
    key: 'Gewichtsreduktion',
    label: 'Gewicht reduzieren',
    hint: 'Hoher Umsatz, moderate Intensität, gut verträglich.',
  },
  {
    key: 'Gesundheit',
    label: 'Fitness und Gesundheit erhalten',
    hint: 'Regelmäßig bewegen, Form halten statt steigern.',
  },
  {
    key: 'Erstfinish',
    label: 'Distanz erstmals finishen',
    hint: 'Ankommen zählt, die Zeit nicht.',
  },
]

export const RACE_DISTANCES: Record<Discipline, string[]> = {
  run: ['5 km', '10 km', 'Halbmarathon', 'Marathon', 'Ultra / Trail'],
  bike: ['Kriterium', 'Straßenrennen', 'Gran Fondo', 'Zeitfahren', 'Marathon / Ultra'],
  swim: ['400 m', '800 m', '1500 m', 'Freiwasser 2,5 km', 'Freiwasser 5 km'],
  triathlon: [
    'Sprintdistanz',
    'Olympische Distanz',
    'Mitteldistanz (70.3)',
    'Langdistanz (Ironman)',
    'Cross-Triathlon',
  ],
}

export const SUPPLEMENTAL_OPTIONS = [
  {
    key: 'strength',
    label: 'Bodyworkout / Krafttraining',
    hint: 'Rumpf, Beine, Stabilität — schützt vor Verletzungen.',
  },
  {
    key: 'mobility',
    label: 'Dehn- und Mobilitätseinheiten',
    hint: 'Einheiten für Beweglichkeit und Regeneration.',
  },
]

export const EQUIPMENT_OPTIONS = [
  { key: 'pool', label: 'Hallenbad / Schwimmbad' },
  { key: 'open_water', label: 'Freiwasser' },
  { key: 'smart_trainer', label: 'Rolle / Smart Trainer' },
  { key: 'powermeter', label: 'Wattmessung am Rad' },
  { key: 'hr_strap', label: 'Brustgurt für Herzfrequenz' },
  { key: 'gym', label: 'Fitnessstudio' },
  { key: 'home_weights', label: 'Gewichte zu Hause' },
  { key: 'treadmill', label: 'Laufband' },
  { key: 'track', label: 'Laufbahn / Tartanbahn' },
  { key: 'trails', label: 'Trails / Gelände' },
  { key: 'gps_watch', label: 'GPS-Uhr' },
]

export const INTENSITY_ZONE_COLOR: Record<string, string> = {
  Z1: 'var(--zone-1)',
  Z2: 'var(--zone-2)',
  Z3: 'var(--zone-3)',
  Z4: 'var(--zone-4)',
  Z5: 'var(--zone-5)',
}

export function weekdayLabel(key: string): string {
  return WEEKDAYS.find((d) => d.key === key)?.label ?? key
}

export function sportLabel(sport: string): string {
  return SPORT_LABEL[sport as Sport] ?? sport
}

export function sportIcon(sport: string): string {
  return SPORT_ICON[sport as Sport] ?? '•'
}

export function sessionTypeLabel(type: string): string {
  return SESSION_TYPE_LABEL[type] ?? type
}

/** Tempoangabe je Sportart.
 *
 * Radfahrer denken in Geschwindigkeit, Schwimmer in Zeit je 100 m, Läufer in
 * Zeit je Kilometer. `avg_pace` speichert nur den blanken Wert — die Einheit
 * ergibt sich aus der Sportart und muss deshalb überall dort mitgeliefert
 * werden, wo der Wert erfasst oder angezeigt wird.
 */
const PACE_FORMAT: Record<string, { label: string; unit: string; example: string }> = {
  bike: { label: 'Geschwindigkeit', unit: 'km/h', example: '31.5' },
  swim: { label: 'Pace', unit: 'min/100 m', example: '1:52' },
}

const PACE_FORMAT_DEFAULT = { label: 'Pace', unit: 'min/km', example: '5:26' }

export function paceFormat(sport: string): { label: string; unit: string; example: string } {
  return PACE_FORMAT[sport] ?? PACE_FORMAT_DEFAULT
}

/** Schlafdauer als „7 h 24 min".
 *
 * Als Dezimalstunde („7.4 h") liest sich der Nachkommateil wie Minuten und ist
 * doch keiner — 7.4 h sind 7 h 24 min, nicht 7 h 40 min.
 */
export function schlafdauer(sekunden: number): string {
  const minutenGesamt = Math.round(sekunden / 60)
  const stunden = Math.floor(minutenGesamt / 60)
  const minuten = minutenGesamt % 60
  return stunden > 0 ? `${stunden} h ${minuten} min` : `${minuten} min`
}
