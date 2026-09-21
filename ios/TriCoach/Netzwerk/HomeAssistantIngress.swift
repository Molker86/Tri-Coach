import Foundation

/// Der Weg durch den Home-Assistant-Ingress — derselbe, den die Companion-App
/// für Add-on-Panels geht:
///
/// 1. Anmeldung am WebSocket mit dem Langzeit-Token,
/// 2. das Add-on finden (`get_panels`) und seine Ingress-Adresse erfragen
///    (`supervisor/api` → `/addons/<slug>/info`),
/// 3. eine Ingress-Sitzung anlegen (`/ingress/session`).
///
/// Danach geht jede Anfrage an `<ha>/api/hassio_ingress/<token>/api/…` mit dem
/// Cookie `ingress_session`. Der Supervisor lässt eine Sitzung nach einigen
/// Minuten verfallen; der Client holt dann einfach eine neue.
actor HomeAssistantIngress {
    private let basis: String
    private let token: String
    private let urlSession: URLSession
    private var addonSlug: String?
    private var ingressPfad: String?
    private var sitzung: String?
    private var laufend: Task<(pfad: String, sitzung: String), Error>?

    init(basis: String, token: String, addonSlug: String?, urlSession: URLSession) {
        self.basis = basis
        self.token = token
        self.addonSlug = addonSlug
        self.urlSession = urlSession
    }

    /// Ingress-Pfad (ohne Schrägstrich am Ende) und Sitzungskennung.
    func zugang(erneuern: Bool = false) async throws -> (pfad: String, sitzung: String) {
        if erneuern { sitzung = nil }
        if let ingressPfad, let sitzung { return (ingressPfad, sitzung) }
        // Mehrere Anfragen zugleich teilen sich eine Aushandlung.
        if let laufend { return try await laufend.value }

        let aufgabe = Task { try await self.aushandeln() }
        laufend = aufgabe
        defer { laufend = nil }
        let ergebnis = try await aufgabe.value
        ingressPfad = ergebnis.pfad
        sitzung = ergebnis.sitzung
        return ergebnis
    }

    private func aushandeln() async throws -> (pfad: String, sitzung: String) {
        guard let url = websocketURL() else { throw APIFehler.ungueltigeAdresse }
        protokolliere("WebSocket öffnen: \(url.absoluteString)")
        let ws = HAWebSocket(url: url, session: urlSession)
        defer { ws.schliessen() }
        try await ws.anmelden(token: token)
        protokolliere("WebSocket: bei Home Assistant angemeldet")

        let pfad: String
        if let bekannt = ingressPfad {
            pfad = bekannt
        } else {
            var slug = addonSlug
            if slug == nil { slug = try await sucheAddon(ws) }
            guard let slug else { throw APIFehler.homeAssistant("Add-on nicht gefunden.") }

            let info = try await ws.befehl([
                "type": "supervisor/api",
                "endpoint": "/addons/\(slug)/info",
                "method": "get",
            ]) as? [String: Any]
            guard let info else {
                throw APIFehler.homeAssistant("Home Assistant lieferte keine Angaben zum Add-on „\(slug)“.")
            }
            if let zustand = info["state"] as? String, zustand != "started" {
                throw APIFehler.homeAssistant("Das Tri-Coach-Add-on läuft gerade nicht (Zustand: \(zustand)).")
            }
            guard let roh = info["ingress_url"] as? String, !roh.isEmpty else {
                throw APIFehler.homeAssistant("Das Add-on „\(slug)“ meldet keine Ingress-Adresse.")
            }
            pfad = roh.hasSuffix("/") ? String(roh.dropLast()) : roh
            addonSlug = slug
            #if DEBUG && targetEnvironment(simulator)
            Diagnose.protokoll("Ingress: Add-on \(slug), Pfad \(pfad)")
            #endif
        }

        let antwort = try await ws.befehl([
            "type": "supervisor/api",
            "endpoint": "/ingress/session",
            "method": "post",
        ]) as? [String: Any]
        protokolliere("Ingress-Sitzung: \(antwort?["session"] != nil ? "erhalten" : "FEHLT")")
        guard let neu = antwort?["session"] as? String, !neu.isEmpty else {
            throw APIFehler.homeAssistant("Home Assistant hat keine Ingress-Sitzung ausgestellt.")
        }
        return (pfad, neu)
    }

    /// Das Add-on steht als Panel in der Seitenleiste; sein Slug ist `tricoach`
    /// mit dem Kürzel des Repositorys davor (z. B. `a1b2c3d4_tricoach`).
    private func sucheAddon(_ ws: HAWebSocket) async throws -> String {
        if let panels = try await ws.befehl(["type": "get_panels"]) as? [String: Any] {
            for case let panel as [String: Any] in panels.values {
                if let config = panel["config"] as? [String: Any],
                   let ingress = config["ingress"] as? String,
                   Self.istTriCoach(ingress) {
                    return ingress
                }
            }
        }
        // Rückfall für Administratoren: die Liste aller Add-ons.
        if let daten = try? await ws.befehl([
            "type": "supervisor/api",
            "endpoint": "/addons",
            "method": "get",
        ]) as? [String: Any],
           let addons = daten["addons"] as? [[String: Any]] {
            for addon in addons {
                if let slug = addon["slug"] as? String, Self.istTriCoach(slug) { return slug }
            }
        }
        throw APIFehler.homeAssistant(
            "Das Tri-Coach-Add-on wurde nicht gefunden. Trage seinen Slug in der Verbindung ein – er steht in der Adresszeile der Add-on-Seite (z. B. a1b2c3d4_tricoach)."
        )
    }

    private static func istTriCoach(_ slug: String) -> Bool {
        slug == "tricoach" || slug.hasSuffix("_tricoach")
    }

    private func websocketURL() -> URL? {
        guard var teile = URLComponents(string: basis) else { return nil }
        teile.scheme = teile.scheme?.lowercased() == "https" ? "wss" : "ws"
        let pfad = teile.path.hasSuffix("/") ? String(teile.path.dropLast()) : teile.path
        teile.path = pfad + "/api/websocket"
        return teile.url
    }
}

/// Minimaler Client für die WebSocket-API von Home Assistant.
final class HAWebSocket {
    private let aufgabe: URLSessionWebSocketTask
    private var naechsteID = 1

    init(url: URL, session: URLSession) {
        aufgabe = session.webSocketTask(with: url)
        aufgabe.resume()
    }

    func anmelden(token: String) async throws {
        let begruessung = try await empfangen()
        protokolliere("WebSocket: Begrüßung \(begruessung["type"] as? String ?? "?") (HA \(begruessung["ha_version"] as? String ?? "?"))")
        guard begruessung["type"] as? String == "auth_required" else {
            throw APIFehler.homeAssistant("Unter dieser Adresse antwortet kein Home Assistant.")
        }
        try await senden(["type": "auth", "access_token": token])
        let antwort = try await empfangen()
        protokolliere("WebSocket: Anmeldung → \(antwort["type"] as? String ?? "?")")
        switch antwort["type"] as? String {
        case "auth_ok":
            return
        case "auth_invalid":
            throw APIFehler.homeAssistant("Home Assistant hat das Token abgelehnt. Prüfe den Langzeit-Zugangstoken.")
        default:
            throw APIFehler.homeAssistant("Die Anmeldung bei Home Assistant ist fehlgeschlagen.")
        }
    }

    func befehl(_ nachricht: [String: Any]) async throws -> Any? {
        let id = naechsteID
        naechsteID += 1
        var mitID = nachricht
        mitID["id"] = id
        try await senden(mitID)
        while true {
            let antwort = try await empfangen()
            guard (antwort["id"] as? Int) == id, antwort["type"] as? String == "result" else { continue }
            if antwort["success"] as? Bool == true { return antwort["result"] }
            let fehler = antwort["error"] as? [String: Any]
            let text = fehler?["message"] as? String ?? "unbekannter Fehler"
            throw APIFehler.homeAssistant("Home Assistant: \(text)")
        }
    }

    func schliessen() {
        aufgabe.cancel(with: .normalClosure, reason: nil)
    }

    private func senden(_ objekt: [String: Any]) async throws {
        let daten = try JSONSerialization.data(withJSONObject: objekt)
        do {
            try await aufgabe.send(.string(String(decoding: daten, as: UTF8.self)))
        } catch {
            throw APIFehler.netzwerk(netzwerkFehlertext(error))
        }
    }

    private func empfangen() async throws -> [String: Any] {
        let nachricht: URLSessionWebSocketTask.Message
        do {
            nachricht = try await aufgabe.receive()
        } catch {
            throw APIFehler.netzwerk(netzwerkFehlertext(error))
        }
        let daten: Data
        switch nachricht {
        case .string(let text): daten = Data(text.utf8)
        case .data(let roh): daten = roh
        @unknown default: daten = Data()
        }
        guard let objekt = try? JSONSerialization.jsonObject(with: daten) as? [String: Any] else {
            throw APIFehler.homeAssistant("Unlesbare Antwort von Home Assistant.")
        }
        return objekt
    }
}
