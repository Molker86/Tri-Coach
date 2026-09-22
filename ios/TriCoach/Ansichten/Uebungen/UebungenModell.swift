import Foundation
import Observation

/// Die Übungen einer Einheit samt Animationen — und der Lauf, der fehlende erzeugt.
///
/// Gehört zur Detailansicht einer Einheit und lebt mit ihr: Die Übungsansicht
/// bekommt dasselbe Objekt, damit ein Freigeben oder Verwerfen dort sofort in
/// der Liste steht, ohne neu zu laden.
@MainActor
@Observable
final class UebungenModell {
    let einheit: PlanEinheit
    var einheitID: Int { einheit.id }
    private(set) var uebungen: [EinheitUebung] = []
    private(set) var fehlend = 0
    /// Der jüngste Animationslauf des Kontos — läuft er, fragt das Modell nach.
    private(set) var lauf: KiLauf?
    private(set) var laedt = false
    private(set) var geladen = false
    private(set) var startetLauf = false
    var fehler: String?

    @ObservationIgnored private weak var app: AppZustand?
    @ObservationIgnored private var abfrage: Task<Void, Never>?

    init(einheit: PlanEinheit) {
        self.einheit = einheit
    }

    func laden(_ app: AppZustand) async {
        self.app = app
        laedt = true
        defer { laedt = false }
        do {
            let daten = try await app.uebungen(einheit: einheitID)
            uebungen = daten.uebungen
            fehlend = daten.fehlend
            lauf = daten.erzeugung
            fehler = nil
            geladen = true
            protokolliere(
                "Übungen der Einheit \(einheitID): \(daten.uebungen.count), ohne Animation \(daten.fehlend)"
                    + (daten.erzeugung.map { " | letzter Lauf \($0.id) \($0.state)" } ?? "")
            )
            if lauf?.laeuft == true { beobachteLauf() }
        } catch APIFehler.server(status: 404, meldung: "Not Found") {
            // FastAPIs eigene Antwort auf einen unbekannten Pfad — nicht die
            // eigene „Einheit nicht gefunden.“: Das Add-on ist älter als 4.6.0.
            #if DEBUG && targetEnvironment(simulator)
            if let ersatz = Entwicklungsbibliothek.uebungen(fuer: einheit) {
                protokolliere("Add-on kennt /animationen noch nicht — Übungen aus der Bibliothek im Repo")
                uebungen = ersatz.uebungen
                fehlend = ersatz.fehlend
                lauf = nil
                fehler = nil
                geladen = true
                return
            }
            #endif
            fehler = "Das Tri-Coach-Add-on kennt noch keine Übungsanimationen. Bitte in Home Assistant auf Version 4.6.0 oder neuer aktualisieren."
        } catch {
            fehler = error.localizedDescription
        }
    }

    /// Stößt den Lauf an, der die fehlenden Animationen von Claude beschreiben lässt.
    func erzeugen() async {
        guard let app else { return }
        startetLauf = true
        defer { startetLauf = false }
        do {
            lauf = try await app.animationenErzeugen()
            fehler = nil
            beobachteLauf()
        } catch {
            fehler = error.localizedDescription
        }
    }

    func freigeben(_ schluessel: String) async throws {
        guard let app else { return }
        let neu = try await app.animationFreigeben(schluessel)
        ersetze(schluessel, durch: neu)
    }

    func verwerfen(_ schluessel: String, rueckmeldung: String) async throws {
        guard let app else { return }
        _ = try await app.animationVerwerfen(schluessel, rueckmeldung: rueckmeldung)
        ersetze(schluessel, durch: nil)
    }

    /// Fragt alle paar Sekunden nach, bis der Lauf fertig ist, und lädt dann neu.
    /// Ein Lauf dauert Minuten — wer die Seite so lange offen hat, soll das
    /// Ergebnis ohne Zutun sehen.
    private func beobachteLauf() {
        abfrage?.cancel()
        abfrage = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(4))
                guard let self, let app = self.app, let id = self.lauf?.id else { return }
                guard let neu = try? await app.kiLauf(id) else { continue }
                self.lauf = neu
                if !neu.laeuft {
                    await self.laden(app)
                    return
                }
            }
        }
    }

    private func ersetze(_ schluessel: String, durch animation: UebungsAnimation?) {
        uebungen = uebungen.map { u in
            guard u.animation?.schluessel == schluessel else { return u }
            return EinheitUebung(zeile: u.zeile, nameEn: u.nameEn, schluessel: u.schluessel, animation: animation)
        }
        fehlend = uebungen.filter { $0.animation == nil }.count
    }
}
