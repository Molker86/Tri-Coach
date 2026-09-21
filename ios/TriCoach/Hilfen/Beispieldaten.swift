#if DEBUG
import Foundation

/// Erfundene Beispieldaten für die SwiftUI-Vorschauen — relativ zu heute, damit
/// der Kalender immer etwas zeigt. Sie laufen durch denselben Decoder wie die
/// echte API und prüfen damit nebenbei die Modelle.
enum Beispieldaten {
    private static func tag(_ versatz: Int) -> String {
        let datum = Datum.kalender.date(byAdding: .day, value: versatz, to: Date()) ?? Date()
        return Datum.schluessel(datum)
    }

    private static func dekodiere<T: Decodable>(_ json: String) -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(T.self, from: Data(json.utf8))
        } catch {
            fatalError("Beispieldaten passen nicht zum Modell: \(error)")
        }
    }

    static let plan: TrainingsPlan = dekodiere("""
    {
      "id": 7, "request_id": 3, "title": "Grundlage festigen, Lauf behutsam steigern",
      "summary": "Rad in Z2 trägt den Umfang, zwei kurze Läufe mit harter Pulsgrenze, eine Schwelleneinheit auf der Rolle.",
      "coaching_notes": "HF-Deckel beim Laufen 148 bpm. Hüftabduktoren zweimal pro Woche.",
      "start_date": "\(tag(-2))", "end_date": "\(tag(5))", "is_active": true,
      "created_at": "2026-09-19T07:02:11Z",
      "sessions": [
        {"id": 101, "date": "\(tag(-2))", "week_number": 1, "order_in_day": 1, "sport": "bike", "session_type": "endurance",
         "title": "Lockere Ausfahrt", "description": "Flach, gleichmäßig.", "structure": "10 min einrollen\\n70 min Z2\\n10 min ausrollen",
         "purpose": "Aerobe Basis", "duration_min": 90, "distance_km": 42.5, "intensity_zone": "Z2",
         "target_hr_low": 128, "target_hr_high": 145, "target_pace": null, "target_power": "150–175 W", "rpe_target": 3,
         "swim_location": null, "bike_location": "outdoor", "logged": true,
         "angepasst_am": null, "anpassungswunsch": null, "anpassungsbegruendung": null},
        {"id": 102, "date": "\(tag(0))", "week_number": 1, "order_in_day": 1, "sport": "run", "session_type": "easy",
         "title": "Lockerer Lauf mit Pulsdeckel", "description": "Auf flachem Untergrund.", "structure": "5 min gehen/traben\\n30 min locker ≤ 148 bpm\\n5 min auslaufen",
         "purpose": "Laufumfang behutsam aufbauen", "duration_min": 40, "distance_km": 6.5, "intensity_zone": "Z2",
         "target_hr_low": 130, "target_hr_high": 148, "target_pace": "6:00–6:30 /km", "target_power": null, "rpe_target": 3,
         "swim_location": null, "bike_location": null, "logged": false,
         "angepasst_am": "2026-09-21T05:31:00Z", "anpassungswunsch": "Knie zwickt leicht",
         "anpassungsbegruendung": "Um 10 Minuten gekürzt, Intensität unverändert."},
        {"id": 103, "date": "\(tag(0))", "week_number": 1, "order_in_day": 2, "sport": "strength", "session_type": "strength",
         "title": "Hüfte & Rumpf", "description": null, "structure": "3× 12 Clamshells\\n3× 10 Seitstütz je Seite\\n3× 12 Monster Walks",
         "purpose": "Gluteus medius stärken", "duration_min": 25, "distance_km": null, "intensity_zone": null,
         "target_hr_low": null, "target_hr_high": null, "target_pace": null, "target_power": null, "rpe_target": null,
         "swim_location": null, "bike_location": null, "logged": false,
         "angepasst_am": null, "anpassungswunsch": null, "anpassungsbegruendung": null},
        {"id": 104, "date": "\(tag(1))", "week_number": 1, "order_in_day": 1, "sport": "swim", "session_type": "technique",
         "title": "Technik im Becken", "description": null, "structure": "400 m ein\\n8× 50 m Technik\\n6× 100 m locker\\n200 m aus",
         "purpose": null, "duration_min": 50, "distance_km": 1.8, "intensity_zone": "Z1–Z2",
         "target_hr_low": null, "target_hr_high": null, "target_pace": "2:05 /100 m", "target_power": null, "rpe_target": 4,
         "swim_location": "pool", "bike_location": null, "logged": false,
         "angepasst_am": null, "anpassungswunsch": null, "anpassungsbegruendung": null},
        {"id": 105, "date": "\(tag(2))", "week_number": 1, "order_in_day": 1, "sport": "bike", "session_type": "threshold",
         "title": "Schwelle auf der Rolle", "description": null, "structure": "15 min ein\\n3× 10 min @ 95 % FTP, 5 min Pause\\n10 min aus",
         "purpose": "Schwellenleistung", "duration_min": 70, "distance_km": null, "intensity_zone": "Z4",
         "target_hr_low": null, "target_hr_high": 165, "target_pace": null, "target_power": "230–240 W", "rpe_target": 7,
         "swim_location": null, "bike_location": "indoor", "logged": false,
         "angepasst_am": null, "anpassungswunsch": null, "anpassungsbegruendung": null},
        {"id": 106, "date": "\(tag(3))", "week_number": 1, "order_in_day": 1, "sport": "rest", "session_type": "rest",
         "title": "Ruhetag", "description": "Spaziergang erlaubt.", "structure": null, "purpose": null,
         "duration_min": null, "distance_km": null, "intensity_zone": null, "target_hr_low": null, "target_hr_high": null,
         "target_pace": null, "target_power": null, "rpe_target": null, "swim_location": null, "bike_location": null,
         "logged": false, "angepasst_am": null, "anpassungswunsch": null, "anpassungsbegruendung": null},
        {"id": 107, "date": "\(tag(4))", "week_number": 1, "order_in_day": 1, "sport": "brick", "session_type": "brick",
         "title": "Koppeleinheit", "description": null, "structure": "60 min Rad Z2\\ndirekt 15 min Lauf locker",
         "purpose": "Wechsel üben", "duration_min": 75, "distance_km": null, "intensity_zone": "Z2",
         "target_hr_low": null, "target_hr_high": 148, "target_pace": null, "target_power": null, "rpe_target": 4,
         "swim_location": null, "bike_location": "outdoor", "logged": false,
         "angepasst_am": null, "anpassungswunsch": null, "anpassungsbegruendung": null}
      ]
    }
    """)

    static let absolviert: [AbsolvierteEinheit] = dekodiere("""
    [
      {"id": 900, "created_at": "2026-09-19T12:00:00Z", "plan_session_id": 101, "date": "\(tag(-2))", "sport": "bike",
       "status": "completed", "duration_min": 92.4, "distance_km": 43.1, "avg_hr": 138, "max_hr": 151,
       "avg_pace": "28.0", "avg_power": null, "calories": 812, "rpe": 3, "source": "garmin",
       "garmin_activity_type": "road_biking", "notes": null},
      {"id": 901, "created_at": "2026-09-18T12:00:00Z", "plan_session_id": null, "date": "\(tag(-3))", "sport": "run",
       "status": "completed", "duration_min": 31, "distance_km": 5.02, "avg_hr": 143, "max_hr": 150,
       "avg_pace": "6:10", "avg_power": null, "calories": 350, "rpe": 3, "source": "garmin",
       "garmin_activity_type": "running", "notes": null}
    ]
    """)

    static let ernaehrung: Ernaehrungsplan = dekodiere("""
    {
      "id": 12, "plan_id": 7, "created_at": "2026-09-19T08:00:00Z",
      "start_date": "\(tag(-1))", "end_date": "\(tag(2))",
      "title": "Ernährung zum Grundlagenblock",
      "summary": "Kohlenhydrate an die Einheiten gekoppelt, Protein gleichmäßig über den Tag.",
      "begruendung": "An Rad- und Schwellentagen mehr Kohlenhydrate vor und nach der Einheit, an Ruhetagen weniger.",
      "tage": [
        {"id": 1, "date": "\(tag(0))", "trainingshinweis": "Lockerer Lauf am Morgen, abends Kraft",
         "kalorien_kcal": 2650, "kohlenhydrate_g": 330, "protein_g": 150, "fett_g": 80, "fluessigkeit_ml": 3000,
         "notiz": "Beim Lauf reicht Wasser.",
         "mahlzeiten": [
           {"id": 11, "order_in_day": 1, "zeitpunkt": "06:30", "name": "Haferbrei mit Banane", "beschreibung": "Mit Milch und etwas Honig.",
            "bezug": "vor", "kalorien_kcal": 520, "kohlenhydrate_g": 85, "protein_g": 20, "fett_g": 10,
            "zutaten": [{"id": 1, "name": "Haferflocken", "menge": 80, "einheit": "g"}, {"id": 2, "name": "Banane", "menge": 1, "einheit": "Stück"}, {"id": 3, "name": "Milch", "menge": 250, "einheit": "ml"}]},
           {"id": 12, "order_in_day": 2, "zeitpunkt": "direkt nach dem Lauf", "name": "Skyr mit Beeren", "beschreibung": null,
            "bezug": "nach", "kalorien_kcal": 280, "kohlenhydrate_g": 30, "protein_g": 30, "fett_g": 2, "zutaten": []},
           {"id": 13, "order_in_day": 3, "zeitpunkt": "12:30", "name": "Vollkornpasta mit Linsenbolognese", "beschreibung": null,
            "bezug": null, "kalorien_kcal": 780, "kohlenhydrate_g": 110, "protein_g": 38, "fett_g": 18, "zutaten": []},
           {"id": 14, "order_in_day": 4, "zeitpunkt": "19:00", "name": "Lachs, Kartoffeln, Brokkoli", "beschreibung": null,
            "bezug": "nach", "kalorien_kcal": 720, "kohlenhydrate_g": 70, "protein_g": 45, "fett_g": 28, "zutaten": []}
         ],
         "einnahmen": [{"id": 21, "order_in_day": 1, "zeitpunkt": "07:00", "name": "Vitamin D3", "dosierung": "2000 IE", "bezug": null},
                       {"id": 22, "order_in_day": 2, "zeitpunkt": "nach der Krafteinheit", "name": "Kreatin", "dosierung": "5 g", "bezug": "nach"}]},
        {"id": 2, "date": "\(tag(1))", "trainingshinweis": "Technik im Becken", "kalorien_kcal": 2450, "kohlenhydrate_g": 290,
         "protein_g": 145, "fett_g": 78, "fluessigkeit_ml": 2800, "notiz": null, "mahlzeiten": [], "einnahmen": []}
      ],
      "supplemente": [
        {"id": 31, "order_index": 1, "name": "Vitamin D3", "dosierung": "2000 IE", "zeitpunkt": "morgens", "begruendung": "Herbst, wenig Sonne."},
        {"id": 32, "order_index": 2, "name": "Kreatin", "dosierung": "5 g", "zeitpunkt": "täglich", "begruendung": "Unterstützt die Kraftarbeit."}
      ]
    }
    """)
}
#endif
