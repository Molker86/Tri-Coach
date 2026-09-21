import Foundation

/// Spricht mit der Tri-Coach-API — direkt oder durch den HA-Ingress.
///
/// Zwei Arten von 401 werden auseinandergehalten, genau wie im Web-Frontend
/// (`api/client.ts`): Nur die eigene Sitzungsprüfung von Tri-Coach setzt
/// `WWW-Authenticate`. Ein 401 **ohne** den Kopf kommt vom Supervisor und heißt,
/// dass die Ingress-Sitzung abgelaufen ist.
actor TriCoachClient {
    private let verbindung: Verbindung
    private let ingress: HomeAssistantIngress?
    private let urlSession: URLSession
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private(set) var token: String?
    private var kontoID: Int?

    init(verbindung: Verbindung, token: String? = nil, kontoID: Int? = nil) {
        self.verbindung = verbindung
        self.token = token
        self.kontoID = kontoID

        let konfiguration = URLSessionConfiguration.default
        konfiguration.timeoutIntervalForRequest = 20
        // Obergrenze auch für den WebSocket: Ohne sie wartete `receive()` auf
        // eine Antwort, die nie kommt, und der Knopf „Verbinden“ bliebe stumm.
        konfiguration.timeoutIntervalForResource = 30
        konfiguration.httpShouldSetCookies = false
        konfiguration.httpCookieAcceptPolicy = .never
        konfiguration.requestCachePolicy = .reloadIgnoringLocalCacheData
        let session = URLSession(configuration: konfiguration)
        urlSession = session

        if case let .homeAssistant(basis, haToken, slug) = verbindung {
            ingress = HomeAssistantIngress(basis: basis, token: haToken, addonSlug: slug, urlSession: session)
        } else {
            ingress = nil
        }
    }

    // MARK: - Endpunkte

    func konten() async throws -> [Konto] {
        try await abrufen("/auth/users", authentifiziert: false)
    }

    /// Anmeldung ohne Passwort — die Kontoauswahl ist die Anmeldung.
    @discardableResult
    func anmelden(kontoID: Int) async throws -> TokenAntwort {
        let body = try JSONSerialization.data(withJSONObject: ["user_id": kontoID])
        let antwort: TokenAntwort = try await abrufen(
            "/auth/login", methode: "POST", body: body, authentifiziert: false
        )
        token = antwort.accessToken
        self.kontoID = kontoID
        return antwort
    }

    func aktiverPlan() async throws -> TrainingsPlan? {
        try await abrufen("/plans/active")
    }

    func aktiverErnaehrungsplan() async throws -> Ernaehrungsplan? {
        try await abrufen("/ernaehrung/aktiv")
    }

    func absolvierteEinheiten(wochen: Int = 8) async throws -> [AbsolvierteEinheit] {
        try await abrufen("/logs?weeks=\(wochen)")
    }

    // MARK: - Transport

    private func abrufen<T: Decodable>(
        _ endpunkt: String,
        methode: String = "GET",
        body: Data? = nil,
        authentifiziert: Bool = true
    ) async throws -> T {
        if authentifiziert, token == nil {
            guard let kontoID else { throw APIFehler.nichtAngemeldet }
            try await anmelden(kontoID: kontoID)
        }

        var (daten, antwort) = try await senden(endpunkt, methode, body, authentifiziert)

        if ingress != nil, [401, 403].contains(antwort.statusCode), !Self.istTriCoachAbweisung(antwort) {
            (daten, antwort) = try await senden(endpunkt, methode, body, authentifiziert, neueSitzung: true)
        }
        // Das Tri-Coach-Token läuft nach 30 Tagen ab. Weil die Anmeldung nur
        // die Konto-ID braucht, geht das still.
        if authentifiziert, Self.istTriCoachAbweisung(antwort), let kontoID {
            try await anmelden(kontoID: kontoID)
            (daten, antwort) = try await senden(endpunkt, methode, body, authentifiziert)
        }
        #if DEBUG && targetEnvironment(simulator)
        Diagnose.antwort(endpunkt, status: antwort.statusCode, daten: daten)
        #endif
        return try auswerten(daten, antwort)
    }

    private func senden(
        _ endpunkt: String,
        _ methode: String,
        _ body: Data?,
        _ mitToken: Bool,
        neueSitzung: Bool = false
    ) async throws -> (Data, HTTPURLResponse) {
        let basis: String
        var cookie: String?
        switch verbindung {
        case .direkt(let b):
            basis = b
        case .homeAssistant(let b, _, _):
            guard let ingress else { throw APIFehler.nichtAngemeldet }
            let zugang = try await ingress.zugang(erneuern: neueSitzung)
            basis = b + zugang.pfad
            cookie = "ingress_session=\(zugang.sitzung)"
        }

        guard let url = URL(string: basis + "/api" + endpunkt) else { throw APIFehler.ungueltigeAdresse }
        var anfrage = URLRequest(url: url)
        anfrage.httpMethod = methode
        anfrage.setValue("application/json", forHTTPHeaderField: "Accept")
        if let cookie { anfrage.setValue(cookie, forHTTPHeaderField: "Cookie") }
        if mitToken, let token { anfrage.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            anfrage.httpBody = body
            anfrage.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        protokolliere("HTTP \(methode) \(url.host ?? "?")…/api\(endpunkt)")
        do {
            let (daten, antwort) = try await urlSession.data(for: anfrage)
            guard let http = antwort as? HTTPURLResponse else {
                throw APIFehler.netzwerk("Keine gültige Antwort vom Server.")
            }
            return (daten, http)
        } catch let fehler as APIFehler {
            throw fehler
        } catch {
            protokolliere("HTTP-Fehler: \(error)")
            throw APIFehler.netzwerk(netzwerkFehlertext(error))
        }
    }

    private func auswerten<T: Decodable>(_ daten: Data, _ antwort: HTTPURLResponse) throws -> T {
        guard (200..<300).contains(antwort.statusCode) else {
            throw APIFehler.server(
                status: antwort.statusCode,
                meldung: Self.fehlermeldung(daten, status: antwort.statusCode)
            )
        }
        do {
            return try decoder.decode(T.self, from: daten)
        } catch {
            throw APIFehler.dekodierung(Self.dekodierText(error))
        }
    }

    private static func istTriCoachAbweisung(_ antwort: HTTPURLResponse) -> Bool {
        antwort.statusCode == 401 && antwort.value(forHTTPHeaderField: "WWW-Authenticate") != nil
    }

    private static func fehlermeldung(_ daten: Data, status: Int) -> String {
        if let objekt = try? JSONSerialization.jsonObject(with: daten) as? [String: Any] {
            if let detail = objekt["detail"] as? String { return detail }
            if let liste = objekt["detail"] as? [[String: Any]] {
                let text = liste.compactMap { $0["msg"] as? String }.joined(separator: "\n")
                if !text.isEmpty { return text }
            }
        }
        switch status {
        case 401, 403: return "Zugriff verweigert (\(status))."
        case 404: return "Nicht gefunden (404). Ist die Adresse richtig und das Add-on aktuell?"
        case 502, 503, 504: return "Tri-Coach ist gerade nicht erreichbar (\(status)). Läuft das Add-on?"
        default: return "Serverfehler (\(status))."
        }
    }

    private static func dekodierText(_ fehler: Error) -> String {
        guard let fehler = fehler as? DecodingError else { return fehler.localizedDescription }
        func pfad(_ kontext: DecodingError.Context) -> String {
            kontext.codingPath.map { $0.intValue.map(String.init) ?? $0.stringValue }.joined(separator: ".")
        }
        switch fehler {
        case .keyNotFound(let schluessel, let kontext):
            return "Feld „\(schluessel.stringValue)“ fehlt bei \(pfad(kontext))"
        case .typeMismatch(_, let kontext), .valueNotFound(_, let kontext):
            return "Unerwarteter Wert bei \(pfad(kontext))"
        case .dataCorrupted(let kontext):
            return "Kein gültiges JSON (\(pfad(kontext)))"
        @unknown default:
            return fehler.localizedDescription
        }
    }
}
