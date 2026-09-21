import Foundation
import Observation

@MainActor
@Observable
final class AppZustand {
    private enum Ablage {
        static let art = "verbindung.art"
        static let haAdresse = "verbindung.haAdresse"
        static let slug = "verbindung.addonSlug"
        static let direktAdresse = "verbindung.direktAdresse"
        static let konto = "konto"
        static let haToken = "ha-token"
        static let triCoachToken = "tricoach-token"
    }

    // MARK: Einstellungen

    private(set) var entwurf: VerbindungsEntwurf
    private(set) var konto: Konto?

    // MARK: Daten

    private(set) var plan: TrainingsPlan?
    private(set) var ernaehrung: Ernaehrungsplan?
    private(set) var absolviert: [AbsolvierteEinheit] = []
    private(set) var laedt = false
    private(set) var zuletztGeladen: Date?
    var fehlermeldung: String?

    private var einheitenNachTag: [String: [PlanEinheit]] = [:]
    private var absolviertNachTag: [String: [AbsolvierteEinheit]] = [:]
    private var ernaehrungNachTag: [String: ErnaehrungsTag] = [:]

    @ObservationIgnored private var client: TriCoachClient?
    /// Der Client aus „Verbinden" — beim Anmelden wiederverwendet, damit die
    /// Ingress-Sitzung nicht zweimal ausgehandelt wird.
    @ObservationIgnored private var gepruefterClient: (entwurf: VerbindungsEntwurf, client: TriCoachClient)?

    var istEingerichtet: Bool { konto != nil }

    init() {
        let ablage = UserDefaults.standard
        var e = VerbindungsEntwurf()
        if let roh = ablage.string(forKey: Ablage.art), let art = Verbindungsart(rawValue: roh) { e.art = art }
        if let text = ablage.string(forKey: Ablage.haAdresse) { e.homeAssistantAdresse = text }
        if let text = ablage.string(forKey: Ablage.slug) { e.addonSlug = text }
        if let text = ablage.string(forKey: Ablage.direktAdresse) { e.direktAdresse = text }
        e.homeAssistantToken = Schluesselbund.lesen(Ablage.haToken) ?? ""
        #if DEBUG && targetEnvironment(simulator)
        if e.homeAssistantToken.isEmpty, let lokal = Entwicklungszugang.laden() {
            if let adresse = lokal.homeAssistantAdresse, !adresse.isEmpty {
                e.homeAssistantAdresse = adresse
            }
            if let token = lokal.homeAssistantToken?.trimmingCharacters(in: .whitespacesAndNewlines), !token.isEmpty {
                e.homeAssistantToken = token
                e.art = .homeAssistant
            }
        }
        #endif
        entwurf = e
        protokolliere("App gestartet: \(e.art.rawValue), \(e.angezeigteAdresse), Token \(e.homeAssistantToken.isEmpty ? "leer" : "vorhanden")")

        if let daten = ablage.data(forKey: Ablage.konto),
           let gespeichert = try? JSONDecoder().decode(Konto.self, from: daten),
           let verbindung = try? e.verbindung() {
            konto = gespeichert
            client = TriCoachClient(
                verbindung: verbindung,
                token: Schluesselbund.lesen(Ablage.triCoachToken),
                kontoID: gespeichert.id
            )
        }
    }

    // MARK: - Einrichtung

    /// Prüft eine Verbindung und liefert die Konten — gespeichert wird noch nichts.
    func kontenLaden(fuer entwurf: VerbindungsEntwurf) async throws -> [Konto] {
        let neu = TriCoachClient(verbindung: try entwurf.verbindung())
        let konten = try await neu.konten()
        gepruefterClient = (entwurf, neu)
        return konten
    }

    func anmelden(konto: Konto, mit entwurf: VerbindungsEntwurf) async throws {
        let neu: TriCoachClient
        if let geprueft = gepruefterClient, geprueft.entwurf == entwurf {
            neu = geprueft.client
        } else {
            neu = TriCoachClient(verbindung: try entwurf.verbindung())
        }
        let antwort = try await neu.anmelden(kontoID: konto.id)

        speichere(entwurf)
        Schluesselbund.schreiben(antwort.accessToken, Ablage.triCoachToken)
        if let daten = try? JSONEncoder().encode(konto) {
            UserDefaults.standard.set(daten, forKey: Ablage.konto)
        }
        gepruefterClient = nil
        client = neu
        self.entwurf = entwurf
        self.konto = konto
        leeren()
        await laden()
    }

    func abmelden() {
        Schluesselbund.schreiben(nil, Ablage.triCoachToken)
        UserDefaults.standard.removeObject(forKey: Ablage.konto)
        client = nil
        konto = nil
        leeren()
    }

    private func speichere(_ entwurf: VerbindungsEntwurf) {
        let ablage = UserDefaults.standard
        ablage.set(entwurf.art.rawValue, forKey: Ablage.art)
        ablage.set(entwurf.homeAssistantAdresse, forKey: Ablage.haAdresse)
        ablage.set(entwurf.addonSlug, forKey: Ablage.slug)
        ablage.set(entwurf.direktAdresse, forKey: Ablage.direktAdresse)
        Schluesselbund.schreiben(entwurf.homeAssistantToken, Ablage.haToken)
    }

    // MARK: - Daten laden

    func laden() async {
        guard let client, !laedt else { return }
        laedt = true
        defer { laedt = false }

        do {
            let neuerPlan = try await client.aktiverPlan()
            let neueErnaehrung = try await client.aktiverErnaehrungsplan()
            // Der Verlauf ist Beiwerk: Scheitert er, bleiben Plan und Ernährung stehen.
            let neueLogs = (try? await client.absolvierteEinheiten()) ?? absolviert
            uebernehmen(plan: neuerPlan, ernaehrung: neueErnaehrung, absolviert: neueLogs)
            zuletztGeladen = Date()
            #if DEBUG && targetEnvironment(simulator)
            Diagnose.protokoll(
                "Konto \(konto?.id ?? -1) \(konto?.username ?? "–") | Verbindung \(entwurf.art.rawValue) \(entwurf.angezeigteAdresse)"
                + " | Plan \(neuerPlan.map { "\($0.id) „\($0.title)“ \($0.startDate)–\($0.endDate), \($0.sessions.count) Einheiten" } ?? "keiner")"
                + " | Ernährung \(neueErnaehrung.map { "\($0.id) \($0.startDate)–\($0.endDate), \($0.tage.count) Tage" } ?? "keine")"
                + " | Logs \(neueLogs.count) | Zeitzone \(TimeZone.current.identifier) | heute \(Datum.schluessel(Date()))"
            )
            #endif
            fehlermeldung = nil
        } catch {
            fehlermeldung = error.localizedDescription
            #if DEBUG && targetEnvironment(simulator)
            Diagnose.protokoll("Fehler beim Laden: \(error.localizedDescription)")
            #endif
        }

        // Nach einer stillen Neuanmeldung das frische Token behalten.
        if let token = await client.token, token != Schluesselbund.lesen(Ablage.triCoachToken) {
            Schluesselbund.schreiben(token, Ablage.triCoachToken)
        }
    }

    func ladenFallsVeraltet() async {
        if let zuletztGeladen, Date().timeIntervalSince(zuletztGeladen) < 300 { return }
        await laden()
    }

    private func uebernehmen(plan: TrainingsPlan?, ernaehrung: Ernaehrungsplan?, absolviert: [AbsolvierteEinheit]) {
        self.plan = plan
        self.ernaehrung = ernaehrung
        self.absolviert = absolviert

        einheitenNachTag = Dictionary(grouping: plan?.sessions ?? [], by: \.tag)
            .mapValues { liste in liste.sorted { ($0.orderInDay ?? 0) < ($1.orderInDay ?? 0) } }
        absolviertNachTag = Dictionary(grouping: absolviert, by: \.tag)
        ernaehrungNachTag = Dictionary(
            (ernaehrung?.tage ?? []).map { ($0.tag, $0) },
            uniquingKeysWith: { erster, _ in erster }
        )
    }

    private func leeren() {
        uebernehmen(plan: nil, ernaehrung: nil, absolviert: [])
        zuletztGeladen = nil
        fehlermeldung = nil
    }

    #if DEBUG
    /// Nur für SwiftUI-Vorschauen: ein angemeldeter Zustand mit Beispieldaten.
    static func vorschau() -> AppZustand {
        let zustand = AppZustand(nurFuerVorschau: true)
        zustand.konto = Konto(id: 1, username: "Florian")
        zustand.uebernehmen(plan: Beispieldaten.plan, ernaehrung: Beispieldaten.ernaehrung, absolviert: Beispieldaten.absolviert)
        zustand.zuletztGeladen = Date()
        return zustand
    }

    private init(nurFuerVorschau: Bool) {
        entwurf = VerbindungsEntwurf()
    }
    #endif

    #if DEBUG && targetEnvironment(simulator)
    /// Meldet sich beim Start selbst an, wenn `ios/Lokal/zugang.json` ein
    /// Konto nennt — damit lässt sich die App im Simulator ohne Klicks prüfen.
    func automatischAnmelden() async {
        guard konto == nil,
              let name = Entwicklungszugang.laden()?.konto?.trimmingCharacters(in: .whitespaces),
              !name.isEmpty
        else { return }
        protokolliere("Automatische Anmeldung als \(name) …")
        do {
            let konten = try await kontenLaden(fuer: entwurf)
            guard let ziel = konten.first(where: { $0.username.caseInsensitiveCompare(name) == .orderedSame }) else {
                protokolliere("Konto \(name) nicht gefunden. Vorhanden: \(konten.map(\.username).joined(separator: ", "))")
                return
            }
            try await anmelden(konto: ziel, mit: entwurf)
            protokolliere("Automatisch angemeldet als \(ziel.username) (ID \(ziel.id))")
        } catch {
            protokolliere("Automatische Anmeldung fehlgeschlagen: \(error.localizedDescription)")
            fehlermeldung = error.localizedDescription
        }
    }
    #endif

    // MARK: - Abfragen je Tag

    func einheitenAm(_ tag: String) -> [PlanEinheit] { einheitenNachTag[tag] ?? [] }
    func absolviertAm(_ tag: String) -> [AbsolvierteEinheit] { absolviertNachTag[tag] ?? [] }
    func ernaehrungAm(_ tag: String) -> ErnaehrungsTag? { ernaehrungNachTag[tag] }
}
