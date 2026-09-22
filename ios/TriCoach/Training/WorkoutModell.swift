import AudioToolbox
import Foundation
import Observation
import UIKit

/// Führt durch ein Kraft- oder Mobility-Workout — Schritt für Schritt, wie die Uhr.
///
/// Ein zeitgesteuerter Satz läuft ab und schaltet von selbst weiter, ein
/// gezählter wartet aufs Tippen und hat die Soll-Wiederholungen vorbelegt.
/// Vor jedem zeitgesteuerten Satz stehen ein paar Sekunden zum Einnehmen der
/// Position: Der Bauplan kennt keine Pausen, und ein Timer, der schon läuft,
/// während man sich noch hinlegt, stiehlt dem Satz seine Zeit.
///
/// **Alle Zeiten hängen an Zeitpunkten, nicht an einem Zähler.** Wird das
/// Telefon kurz gesperrt, holt der nächste Takt nach, was inzwischen
/// abgelaufen ist — die Sätze behalten ihre wirklichen Anfangs- und Endzeiten,
/// und genau die gehen an Garmin.
@MainActor
@Observable
final class WorkoutModell {
    enum Phase: Equatable {
        case laden
        case bereit
        case vorbereitung
        case aktiv
        case fertig
    }

    enum Versand: Equatable {
        case keiner
        case laeuft
        case angekommen
        /// Gespeichert, aber (noch) nicht in Garmin — mit Grund.
        case offen(String)
    }

    /// Sekunden zum Einnehmen der Position vor einem zeitgesteuerten Satz.
    static let vorbereitungS: TimeInterval = 5

    struct ErledigterSatz: Hashable {
        let schritt: Int
        let uebung: Int
        let beginn: Date
        let dauer: TimeInterval
        let wiederholungen: Int?
    }

    let einheit: PlanEinheit
    private(set) var ablauf: Ablauf?
    private(set) var fehler: String?
    private(set) var phase: Phase = .laden
    private(set) var index = 0
    private(set) var pausiert = false
    private(set) var erledigt: [ErledigterSatz] = []
    private(set) var beginn: Date?
    private(set) var ende: Date?
    private(set) var versand: Versand = .keiner
    /// Die gezählten Wiederholungen des laufenden Satzes — vorbelegt mit dem Soll.
    var wiederholungen = 0

    /// Wird bei jedem Takt neu gesetzt; die Ansicht liest daraus Countdown und Uhr.
    private(set) var jetzt = Date()

    @ObservationIgnored private weak var app: AppZustand?
    @ObservationIgnored private var takt: Task<Void, Never>?
    @ObservationIgnored private var schrittBeginn: Date?
    @ObservationIgnored private var schrittPause: TimeInterval = 0
    /// Ende der Vorbereitung bzw. des zeitgesteuerten Satzes.
    @ObservationIgnored private var faellig: Date?
    @ObservationIgnored private var pausiertSeit: Date?
    @ObservationIgnored private var pausiertGesamt: TimeInterval = 0
    @ObservationIgnored private var letzterPieps: Int?
    @ObservationIgnored private let kennung = UUID().uuidString

    init(einheit: PlanEinheit) {
        self.einheit = einheit
    }

    // MARK: - Abfragen für die Ansicht

    var schritte: [AblaufSchritt] { ablauf?.schritte ?? [] }
    var schritt: AblaufSchritt? { schritte.indices.contains(index) ? schritte[index] : nil }
    var naechster: AblaufSchritt? { schritte.indices.contains(index + 1) ? schritte[index + 1] : nil }

    func uebung(_ schritt: AblaufSchritt?) -> AblaufUebung? {
        guard let schritt, let ablauf, ablauf.uebungen.indices.contains(schritt.uebung) else { return nil }
        return ablauf.uebungen[schritt.uebung]
    }

    /// Sekunden bis zum Ende der Vorbereitung oder des zeitgesteuerten Satzes.
    var verbleibend: TimeInterval? {
        guard let faellig else { return nil }
        let bezug = pausiertSeit ?? jetzt
        return max(0, faellig.timeIntervalSince(bezug))
    }

    /// Wie lange der laufende Satz schon dauert (ohne Pausen).
    var imSatz: TimeInterval {
        guard let schrittBeginn, phase == .aktiv else { return 0 }
        let bezug = pausiertSeit ?? jetzt
        return max(0, bezug.timeIntervalSince(schrittBeginn) - schrittPause)
    }

    /// Die Dauer des Workouts bis jetzt, ohne Pausen.
    var gesamtdauer: TimeInterval {
        guard let beginn else { return 0 }
        let bezug = ende ?? pausiertSeit ?? jetzt
        return max(0, bezug.timeIntervalSince(beginn) - pausiertGesamt)
    }

    var wiederholungenGesamt: Int { erledigt.compactMap(\.wiederholungen).reduce(0, +) }

    // MARK: - Laden und Starten

    func laden(_ app: AppZustand) async {
        self.app = app
        guard ablauf == nil else { return }
        do {
            let geladen = try await app.ablauf(einheit: einheit.id)
            guard !geladen.schritte.isEmpty else {
                fehler = "Diese Einheit enthält keine Übung, die sich Schritt für Schritt führen ließe."
                return
            }
            ablauf = geladen
            phase = .bereit
            protokolliere("Workout \(einheit.id): \(geladen.schritte.count) Schritte aus \(geladen.quelle)")
        } catch APIFehler.server(status: 404, meldung: "Not Found") {
            #if DEBUG && targetEnvironment(simulator)
            if let ersatz = Entwicklungsbibliothek.ablauf(fuer: einheit) {
                protokolliere("Add-on kennt /training noch nicht — Ablauf aus dem Aufbautext")
                ablauf = ersatz
                phase = .bereit
                return
            }
            #endif
            fehler = "Das Tri-Coach-Add-on kann noch keine Workouts führen. Bitte in Home Assistant auf die neueste Version aktualisieren."
        } catch {
            fehler = error.localizedDescription
        }
    }

    func starten() {
        guard phase == .bereit else { return }
        let jetzt = Date()
        beginn = jetzt
        self.jetzt = jetzt
        UIApplication.shared.isIdleTimerDisabled = true
        gehe(zu: 0, ab: jetzt)
        taktStarten()
    }

    // MARK: - Bedienung

    /// „Los“ in der Vorbereitung, „Satz fertig“ im Satz.
    func weiter() {
        guard !pausiert else { return }
        let jetzt = Date()
        switch phase {
        case .vorbereitung:
            satzBeginnen(ab: jetzt)
        case .aktiv:
            schliesseSatz(ende: jetzt)
            gehe(zu: index + 1, ab: jetzt)
        default:
            break
        }
    }

    /// Diesen Schritt auslassen — er geht nicht an Garmin.
    func ueberspringen() {
        guard phase == .vorbereitung || phase == .aktiv else { return }
        gehe(zu: index + 1, ab: Date())
    }

    /// Einen Schritt zurück — der dort erledigte Satz wird verworfen und neu gemacht.
    func zurueck() {
        guard index > 0, phase == .vorbereitung || phase == .aktiv else { return }
        erledigt.removeAll { $0.schritt >= index - 1 }
        gehe(zu: index - 1, ab: Date())
    }

    func pauseUmschalten() {
        let jetzt = Date()
        if let seit = pausiertSeit {
            let dauer = jetzt.timeIntervalSince(seit)
            pausiertGesamt += dauer
            if phase == .aktiv { schrittPause += dauer }
            faellig = faellig.map { $0.addingTimeInterval(dauer) }
            pausiertSeit = nil
            pausiert = false
        } else if phase == .vorbereitung || phase == .aktiv {
            pausiertSeit = jetzt
            pausiert = true
        }
        self.jetzt = jetzt
    }

    /// Vorzeitig beenden: Was erledigt ist, gilt — der laufende Satz nicht.
    func beenden() {
        guard phase != .fertig, phase != .laden else { return }
        if pausiert { pauseUmschalten() }
        abschliessen(ende: Date())
    }

    /// Abbrechen ohne zu speichern.
    func verwerfen() {
        takt?.cancel()
        UIApplication.shared.isIdleTimerDisabled = false
        phase = .fertig
        ende = Date()
        versand = .keiner
    }

    func aufraeumen() {
        takt?.cancel()
        UIApplication.shared.isIdleTimerDisabled = false
    }

    // MARK: - Ablauf

    private func gehe(zu neu: Int, ab zeitpunkt: Date) {
        letzterPieps = nil
        guard schritte.indices.contains(neu) else {
            abschliessen(ende: zeitpunkt)
            return
        }
        index = neu
        let schritt = schritte[neu]
        wiederholungen = schritt.wiederholungen ?? 0
        if schritt.art == .zeit {
            phase = .vorbereitung
            faellig = zeitpunkt.addingTimeInterval(Self.vorbereitungS)
            schrittBeginn = nil
        } else {
            satzBeginnen(ab: zeitpunkt)
        }
    }

    private func satzBeginnen(ab zeitpunkt: Date) {
        guard let schritt else { return }
        phase = .aktiv
        schrittBeginn = zeitpunkt
        schrittPause = 0
        letzterPieps = nil
        faellig = schritt.art == .zeit ? zeitpunkt.addingTimeInterval(TimeInterval(schritt.dauerS ?? 0)) : nil
        if schritt.art == .zeit { signal(.start) }
    }

    private func schliesseSatz(ende zeitpunkt: Date) {
        guard let schritt, let schrittBeginn else { return }
        let dauer = max(0, zeitpunkt.timeIntervalSince(schrittBeginn) - schrittPause)
        erledigt.removeAll { $0.schritt == index }
        erledigt.append(ErledigterSatz(
            schritt: index,
            uebung: schritt.uebung,
            beginn: schrittBeginn,
            dauer: dauer,
            wiederholungen: schritt.art == .wiederholungen ? max(0, wiederholungen) : nil
        ))
    }

    private func abschliessen(ende zeitpunkt: Date) {
        takt?.cancel()
        UIApplication.shared.isIdleTimerDisabled = false
        ende = zeitpunkt
        faellig = nil
        phase = .fertig
        signal(.ende)
        guard !erledigt.isEmpty else {
            versand = .offen("Kein Satz erledigt — es wird nichts an Garmin übertragen.")
            return
        }
        Task { await senden() }
    }

    private func taktStarten() {
        takt?.cancel()
        takt = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(200))
                self?.tick(Date())
            }
        }
    }

    /// Ein Takt: Countdown-Signale, und was abgelaufen ist, schließen — auch
    /// mehrere Schritte auf einmal, wenn das Telefon gesperrt war.
    func tick(_ zeitpunkt: Date) {
        jetzt = zeitpunkt
        guard !pausiert else { return }
        var runden = 0
        while let faellig, faellig <= zeitpunkt, runden < 50 {
            runden += 1
            switch phase {
            case .vorbereitung:
                satzBeginnen(ab: faellig)
            case .aktiv:
                schliesseSatz(ende: faellig)
                signal(.satzEnde)
                gehe(zu: index + 1, ab: faellig)
            default:
                self.faellig = nil
            }
        }
        if let rest = verbleibend, rest > 0 {
            let sekunde = Int(rest.rounded(.up))
            if sekunde <= 3, sekunde != letzterPieps {
                letzterPieps = sekunde
                signal(.countdown)
            }
        }
    }

    // MARK: - Signale

    private enum Signal { case countdown, start, satzEnde, ende }

    private func signal(_ art: Signal) {
        switch art {
        case .countdown:
            AudioServicesPlaySystemSound(1103)
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
        case .start:
            AudioServicesPlaySystemSound(1110)
            UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        case .satzEnde:
            AudioServicesPlaySystemSound(1111)
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        case .ende:
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        }
    }

    // MARK: - An Garmin

    var bericht: TrainingsBericht? {
        guard let beginn, let ende, let ablauf else { return nil }
        let saetze = erledigt.sorted { $0.beginn < $1.beginn }.map { satz in
            let uebung = ablauf.uebungen.indices.contains(satz.uebung) ? ablauf.uebungen[satz.uebung] : nil
            return TrainingsBericht.Satz(
                uebung: satz.uebung,
                beginn: satz.beginn,
                dauerS: (satz.dauer * 10).rounded() / 10,
                wiederholungen: satz.wiederholungen,
                kategorie: uebung?.kategorie,
                garminName: uebung?.garminName
            )
        }
        return TrainingsBericht(
            kennung: kennung,
            beginn: beginn,
            ende: ende,
            pausiertS: (pausiertGesamt * 10).rounded() / 10,
            saetze: saetze
        )
    }

    func senden() async {
        guard let app, let bericht else { return }
        versand = .laeuft
        let ergebnis = await app.trainingAbschliessen(einheit: einheit.id, bericht: bericht)
        switch ergebnis {
        case .success(let quittung) where quittung.istHochgeladen:
            versand = .angekommen
        case .success(let quittung):
            versand = .offen(quittung.meldung ?? "Garmin hat das Training noch nicht angenommen.")
        case .failure(let fehler):
            versand = .offen(fehler.localizedDescription)
        }
    }
}
