import Foundation

enum Verbindungsart: String, CaseIterable, Identifiable, Codable {
    /// Über den Home-Assistant-Ingress — der Normalfall, denn nur dort sitzt
    /// die Anmeldung (siehe `docs/backend.md`, „Anmeldung ohne Passwort").
    case homeAssistant
    /// Direkt auf den Server, z. B. das lokale Backend beim Entwickeln.
    case direkt

    var id: String { rawValue }

    var bezeichnung: String {
        switch self {
        case .homeAssistant: "Home Assistant"
        case .direkt: "Direkt"
        }
    }
}

/// Eine geprüfte, vollständige Verbindung.
enum Verbindung: Equatable {
    case direkt(basis: String)
    case homeAssistant(basis: String, token: String, addonSlug: String?)
}

/// Was im Formular steht — darf unvollständig sein.
struct VerbindungsEntwurf: Equatable {
    var art: Verbindungsart = .homeAssistant
    var homeAssistantAdresse = "http://homeassistant.local:8123"
    var homeAssistantToken = ""
    var addonSlug = ""
    var direktAdresse = "http://localhost:8000"

    var angezeigteAdresse: String {
        art == .homeAssistant ? homeAssistantAdresse : direktAdresse
    }

    func verbindung() throws -> Verbindung {
        switch art {
        case .homeAssistant:
            guard let basis = Self.normalisiert(homeAssistantAdresse) else {
                throw APIFehler.ungueltigeAdresse
            }
            let token = homeAssistantToken.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !token.isEmpty else { throw APIFehler.fehlendesToken }
            let slug = addonSlug.trimmingCharacters(in: .whitespacesAndNewlines)
            return .homeAssistant(basis: basis, token: token, addonSlug: slug.isEmpty ? nil : slug)
        case .direkt:
            guard let basis = Self.normalisiert(direktAdresse) else {
                throw APIFehler.ungueltigeAdresse
            }
            return .direkt(basis: basis)
        }
    }

    /// Ergänzt ein fehlendes Schema und schneidet den Schrägstrich am Ende ab.
    static func normalisiert(_ roh: String) -> String? {
        var text = roh.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.contains("://") { text = "http://" + text }
        while text.hasSuffix("/") { text.removeLast() }
        guard let url = URL(string: text),
              let schema = url.scheme?.lowercased(),
              ["http", "https"].contains(schema),
              url.host != nil
        else { return nil }
        return text
    }
}

enum APIFehler: LocalizedError, Equatable {
    case ungueltigeAdresse
    case fehlendesToken
    case nichtAngemeldet
    case netzwerk(String)
    case homeAssistant(String)
    case server(status: Int, meldung: String)
    case dekodierung(String)

    var errorDescription: String? {
        switch self {
        case .ungueltigeAdresse:
            "Die Adresse ist ungültig. Beispiel: http://homeassistant.local:8123"
        case .fehlendesToken:
            "Bitte einen Langzeit-Zugangstoken aus Home Assistant eintragen."
        case .nichtAngemeldet:
            "Nicht angemeldet."
        case .netzwerk(let text), .homeAssistant(let text):
            text
        case .server(_, let meldung):
            meldung
        case .dekodierung(let text):
            "Die Antwort des Servers ließ sich nicht lesen (\(text))."
        }
    }
}

func netzwerkFehlertext(_ fehler: Error) -> String {
    guard let url = fehler as? URLError else { return fehler.localizedDescription }
    switch url.code {
    case .notConnectedToInternet:
        return "Keine Netzwerkverbindung."
    case .cannotFindHost, .cannotConnectToHost, .dnsLookupFailed:
        return "Server nicht erreichbar. Stimmt die Adresse, und bist du im Heimnetz oder per WireGuard verbunden?"
    case .timedOut:
        return "Zeitüberschreitung – der Server antwortet nicht."
    case .secureConnectionFailed, .serverCertificateUntrusted, .serverCertificateHasBadDate:
        return "Die sichere Verbindung ist fehlgeschlagen (Zertifikat)."
    default:
        return url.localizedDescription
    }
}
