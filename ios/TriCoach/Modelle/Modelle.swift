import Foundation

// Spiegeln die Pydantic-Schemas aus `backend/app/schemas.py`.
// Dekodiert wird mit `.convertFromSnakeCase` — `kohlenhydrate_g` wird zu
// `kohlenhydrateG`. Zahlen stehen durchgehend als `Double`: Das Backend
// schreibt manche Felder als int, manche als float, und ein Typwechsel dort
// soll die App nicht brechen.

// MARK: - Anmeldung

/// Eintrag der Kontoauswahl (`/api/auth/users`).
struct Konto: Codable, Identifiable, Hashable {
    let id: Int
    let username: String
}

struct Benutzer: Codable, Hashable {
    let id: Int
    let email: String?
    let username: String
}

struct TokenAntwort: Codable {
    let accessToken: String
    let user: Benutzer
}

// MARK: - Training

struct TrainingsPlan: Codable, Identifiable, Hashable {
    let id: Int
    let title: String
    let summary: String?
    let coachingNotes: String?
    let startDate: String
    let endDate: String
    let isActive: Bool
    let sessions: [PlanEinheit]
}

struct PlanEinheit: Codable, Identifiable, Hashable {
    let id: Int
    let date: String
    let orderInDay: Int?
    let sport: String
    let sessionType: String?
    let title: String
    let description: String?
    let structure: String?
    let purpose: String?
    let durationMin: Double?
    let distanceKm: Double?
    let intensityZone: String?
    let targetHrLow: Double?
    let targetHrHigh: Double?
    let targetPace: String?
    let targetPower: String?
    let rpeTarget: Double?
    let swimLocation: String?
    let bikeLocation: String?
    let logged: Bool?
    let angepasstAm: String?
    let anpassungswunsch: String?
    let anpassungsbegruendung: String?

    var sportart: Sportart { Sportart(sport) }
    var erledigt: Bool { logged ?? false }
    var tag: String { String(date.prefix(10)) }
}

/// Eine absolvierte Einheit aus Garmin (`/api/logs`).
struct AbsolvierteEinheit: Codable, Identifiable, Hashable {
    let id: Int
    let planSessionId: Int?
    let date: String
    let sport: String
    let status: String?
    let durationMin: Double?
    let distanceKm: Double?
    let avgHr: Double?
    let avgPace: String?
    let avgPower: Double?
    let calories: Double?
    let garminActivityType: String?
    let notes: String?

    var sportart: Sportart { Sportart(sport) }
    var tag: String { String(date.prefix(10)) }
}

// MARK: - Ernährung

struct Ernaehrungsplan: Codable, Identifiable, Hashable {
    let id: Int
    let planId: Int?
    let startDate: String
    let endDate: String
    let title: String
    let summary: String?
    let begruendung: String?
    let tage: [ErnaehrungsTag]
    let supplemente: [Supplement]?
}

struct ErnaehrungsTag: Codable, Identifiable, Hashable {
    let id: Int
    let date: String
    let trainingshinweis: String?
    let kalorienKcal: Double?
    let kohlenhydrateG: Double?
    let proteinG: Double?
    let fettG: Double?
    let fluessigkeitMl: Double?
    let notiz: String?
    let mahlzeiten: [Mahlzeit]
    let einnahmen: [Einnahme]?

    var tag: String { String(date.prefix(10)) }
    var mahlzeitenSortiert: [Mahlzeit] {
        mahlzeiten.sorted { ($0.orderInDay ?? 0) < ($1.orderInDay ?? 0) }
    }
    var einnahmenSortiert: [Einnahme] {
        (einnahmen ?? []).sorted { ($0.orderInDay ?? 0) < ($1.orderInDay ?? 0) }
    }
}

struct Mahlzeit: Codable, Identifiable, Hashable {
    let id: Int
    let orderInDay: Int?
    let zeitpunkt: String
    let name: String
    let beschreibung: String?
    let bezug: String?
    let kalorienKcal: Double?
    let kohlenhydrateG: Double?
    let proteinG: Double?
    let fettG: Double?
    let zutaten: [Zutat]?
}

struct Zutat: Codable, Identifiable, Hashable {
    let id: Int
    let name: String
    let menge: Double?
    let einheit: String?
}

/// Eine Supplementgabe an einem Tag.
struct Einnahme: Codable, Identifiable, Hashable {
    let id: Int
    let orderInDay: Int?
    let zeitpunkt: String
    let name: String
    let dosierung: String?
    let bezug: String?
}

/// Eintrag der Supplementliste — dort steht das Wofür.
struct Supplement: Codable, Identifiable, Hashable {
    let id: Int
    let orderIndex: Int?
    let name: String
    let dosierung: String?
    let zeitpunkt: String?
    let begruendung: String?
}
