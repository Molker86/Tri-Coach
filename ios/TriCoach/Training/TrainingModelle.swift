import Foundation

// Spiegeln `AblaufOut`, `AppTrainingIn` und `AppTrainingOut` aus
// `backend/app/schemas.py`. Wortgetreu dekodiert wie die Animationen — die
// Übungen tragen deren Posen mit (siehe `Animation/Bewegung.swift`).

/// Die Einheit Satz für Satz, so wie das Workout auf der Uhr sie führt.
struct Ablauf: Decodable {
    let planSessionId: Int
    let sport: String
    let titel: String
    let quelle: String
    let uebungen: [AblaufUebung]
    let schritte: [AblaufSchritt]

    private enum CodingKeys: String, CodingKey {
        case sport, titel, quelle, uebungen, schritte
        case planSessionId = "plan_session_id"
    }
}

struct AblaufUebung: Decodable, Hashable {
    let nummer: Int
    let titel: String
    let nameEn: String?
    let zeile: String
    let jeSeite: Bool
    let kategorie: String?
    let garminName: String?
    let animation: UebungsAnimation?

    private enum CodingKeys: String, CodingKey {
        case nummer, titel, zeile, kategorie, animation
        case nameEn = "name_en"
        case jeSeite = "je_seite"
        case garminName = "garmin_name"
    }
}

struct AblaufSchritt: Decodable, Hashable {
    enum Art: String, Decodable {
        /// Läuft nach Zeit ab und schaltet von selbst weiter.
        case zeit
        /// Gezählt — weiter per Tippen, die Wiederholungen stehen vorbelegt.
        case wiederholungen
        /// Ohne Maß — weiter per Tippen, wie auf der Uhr per Rundentaste.
        case taste
    }

    let uebung: Int
    let art: Art
    let dauerS: Int?
    let wiederholungen: Int?
    let satz: Int
    let saetze: Int
    let seite: Int?

    private enum CodingKeys: String, CodingKey {
        case uebung, art, wiederholungen, satz, saetze, seite
        case dauerS = "dauer_s"
    }
}

/// Was die App nach dem Workout meldet.
struct TrainingsBericht: Codable, Hashable {
    struct Satz: Codable, Hashable {
        let uebung: Int
        let beginn: Date
        let dauerS: Double
        let wiederholungen: Int?
        let kategorie: String?
        let garminName: String?

        private enum CodingKeys: String, CodingKey {
            case uebung, beginn, wiederholungen, kategorie
            case dauerS = "dauer_s"
            case garminName = "garmin_name"
        }
    }

    /// Von der App vergeben — derselbe Bericht zweimal lädt nicht zweimal hoch.
    let kennung: String
    let beginn: Date
    let ende: Date
    let pausiertS: Double
    let saetze: [Satz]

    private enum CodingKeys: String, CodingKey {
        case kennung, beginn, ende, saetze
        case pausiertS = "pausiert_s"
    }
}

/// Die Antwort auf den Bericht: ob er in Garmin angekommen ist.
struct TrainingsQuittung: Decodable, Hashable {
    let kennung: String
    let planSessionId: Int?
    /// offen | hochgeladen | fehlgeschlagen
    let zustand: String
    let meldung: String?
    let garminActivityId: String?

    var istHochgeladen: Bool { zustand == "hochgeladen" }

    private enum CodingKeys: String, CodingKey {
        case kennung, zustand, meldung
        case planSessionId = "plan_session_id"
        case garminActivityId = "garmin_activity_id"
    }
}
