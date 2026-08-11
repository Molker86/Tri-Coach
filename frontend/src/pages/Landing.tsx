import { Link } from 'react-router-dom'

const FEATURES = [
  {
    icon: '🎯',
    title: 'Fragebogen statt Fragezeichen',
    text: 'Ziel, Trainingstage, Zeitbudget, Ausrüstung und deine Leistungswerte — geclustert abgefragt, mit Freitextfeld für alles Individuelle.',
  },
  {
    icon: '🤖',
    title: 'Plan von der KI',
    text: 'Die App baut aus deinen Angaben einen fertigen Prompt samt Datenpaket. Kopieren, an eine KI schicken, Antwort zurück einfügen.',
  },
  {
    icon: '📅',
    title: 'Die nächsten Tage konkret',
    text: 'Kein Plan auf Monate hinaus, sondern der nächste kurze Block — jede Einheit mit Aufbau, Zielpuls, Pace und Trainingswirkung.',
  },
  {
    icon: '📈',
    title: 'Training erfassen',
    text: 'Puls, Strecke, Zeit, Watt, RPE und Befinden nach jeder Einheit. Daraus entsteht die Grundlage für den nächsten Block.',
  },
  {
    icon: '❤️',
    title: 'Werte jederzeit anpassen',
    text: 'Gewicht, Ruhepuls, VO2max oder HRV ändern sich — deine Herzfrequenzzonen und der nächste Plan ziehen mit.',
  },
  {
    icon: '🔁',
    title: 'Dynamische Fortschreibung',
    text: 'Der nächste Plan kennt die letzten vier Wochen: tatsächlichen Umfang, ausgefallene Einheiten und deine Belastungswerte.',
  },
]

export default function Landing() {
  return (
    <div className="landing">
      <header className="topbar">
        <span className="brand">
          <span className="brand-mark">TC</span>
          Tri-Coach
        </span>
        <div className="spacer" />
        <div className="row">
          <Link className="btn btn-ghost" to="/login">
            Einloggen
          </Link>
          <Link className="btn btn-primary" to="/registrieren">
            Anmelden
          </Link>
        </div>
      </header>

      <section className="landing-hero">
        <span className="badge badge-accent">
          Laufen · Schwimmen · Radfahren · Triathlon
        </span>
        <h1>Dein Trainingsplan, gebaut auf deinen Daten</h1>
        <p className="landing-lead">
          Beantworte einmal die Fragen zu Ziel, Zeit und Leistungswerten. Tri-Coach
          erzeugt daraus ein Datenpaket für die KI und verwandelt deren Antwort in
          die konkreten nächsten Trainingstage — die mit jedem erfassten Training
          besser werden.
        </p>
        <div className="row">
          <Link className="btn btn-primary btn-lg" to="/registrieren">
            Kostenlos anmelden
          </Link>
          <Link className="btn btn-secondary btn-lg" to="/login">
            Ich habe schon ein Konto
          </Link>
        </div>
      </section>

      <section className="landing-features">
        <div className="grid grid-3">
          {FEATURES.map((feature) => (
            <div className="feature" key={feature.title}>
              <div className="feature-icon">{feature.icon}</div>
              <h3>{feature.title}</h3>
              <p>{feature.text}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
