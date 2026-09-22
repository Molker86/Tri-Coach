#if DEBUG && targetEnvironment(simulator)
import Foundation

/// Nur im Simulator und nur im Debug-Build: Adresse und Token aus
/// `ios/Lokal/zugang.json` auf dem Mac vorbelegen.
///
/// Der Grund ist die Zwischenablage: Ein langes HA-Token in den Simulator zu
/// bekommen, scheitert je nach Xcode-Version am Abgleich der Zwischenablage.
/// Die Datei steht in `.gitignore` und gelangt nie ins Repository oder in
/// einen Release-Build. Der Simulator liest das Dateisystem des Macs mit, und
/// `#filePath` zeigt zur Übersetzungszeit auf genau diese Quelldatei.
enum Entwicklungszugang {
    struct Daten: Decodable {
        let homeAssistantAdresse: String?
        let homeAssistantToken: String?
        /// Benutzername in Tri-Coach — ist er gesetzt, meldet sich die App
        /// beim Start selbst an (nur im Simulator).
        let konto: String?
        /// Öffnet nach dem Laden eine Einheit — Kennung oder Sportart.
        let startEinheit: String?
        /// Öffnet darin eine Übung — Schlüssel oder „*“ für die erste.
        let startUebung: String?
    }

    static func laden() -> Daten? {
        let datei = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // Hilfen
            .deletingLastPathComponent()  // TriCoach
            .deletingLastPathComponent()  // ios
            .appendingPathComponent("Lokal/zugang.json")
        guard let daten = try? Data(contentsOf: datei) else { return nil }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try? decoder.decode(Daten.self, from: daten)
    }
}

/// Merkt sich, dass `start_einheit`/`start_uebung` schon gewirkt haben — sonst
/// öffnete jedes Neuladen die Seite ein weiteres Mal.
enum Entwicklungsstart {
    static var einheitGeoeffnet = false
    static var uebungGeoeffnet = false
}
#endif
