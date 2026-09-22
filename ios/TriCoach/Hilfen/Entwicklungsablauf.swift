#if DEBUG && targetEnvironment(simulator)
import Foundation

/// Nur im Simulator-Debug-Build: ein Workout-Ablauf aus dem Aufbautext, wenn
/// das Add-on `/api/training/…` noch nicht kennt.
///
/// Stark vereinfacht gegenüber `garmin/ablauf.py` (nur „3x15“, „3x40 s“,
/// „60 s“ und „je Seite“, kein Bauplan, keine Garmin-Kategorien) — es geht
/// allein darum, die Ansichten zu sehen, bevor das Add-on aktualisiert ist.
extension Entwicklungsbibliothek {
    static func ablauf(fuer einheit: PlanEinheit) -> Ablauf? {
        guard let uebungen = uebungen(fuer: einheit)?.uebungen, !uebungen.isEmpty else { return nil }
        let saetzeMuster = try! NSRegularExpression(pattern: #"(\d{1,2})\s*[x×]\s*(\d{1,4})\s*(s|sek|min)?\b"#, options: .caseInsensitive)
        let einzelMuster = try! NSRegularExpression(pattern: #"(\d{1,4})\s*(s|sek|min)\b"#, options: .caseInsensitive)
        let seiteMuster = try! NSRegularExpression(pattern: #"\b(je|pro)\s+(seite|bein|arm)"#, options: .caseInsensitive)

        func treffer(_ muster: NSRegularExpression, _ text: String) -> [String]? {
            guard let t = muster.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) else { return nil }
            return (0..<t.numberOfRanges).map { i in
                Range(t.range(at: i), in: text).map { String(text[$0]) } ?? ""
            }
        }

        var ablaufUebungen: [AblaufUebung] = []
        var schritte: [AblaufSchritt] = []
        for (nummer, u) in uebungen.enumerated() {
            let jeSeite = treffer(seiteMuster, u.zeile) != nil
            var saetze = 1, dauer: Int?, wdh: Int?
            if let t = treffer(saetzeMuster, u.zeile) {
                saetze = Int(t[1]) ?? 1
                let zahl = Int(t[2]) ?? 0
                if t[3].isEmpty { wdh = zahl } else { dauer = t[3].lowercased().hasPrefix("min") ? zahl * 60 : zahl }
            } else if let t = treffer(einzelMuster, u.zeile) {
                let zahl = Int(t[1]) ?? 0
                dauer = t[2].lowercased().hasPrefix("min") ? zahl * 60 : zahl
            }
            ablaufUebungen.append(AblaufUebung(
                nummer: nummer, titel: u.titel, nameEn: u.nameEn, zeile: u.zeile, jeSeite: jeSeite,
                kategorie: nil, garminName: nil, animation: u.animation
            ))
            let art: AblaufSchritt.Art = dauer != nil ? .zeit : (wdh != nil ? .wiederholungen : .taste)
            for satz in 1...saetze {
                for seite in (jeSeite ? [1, 2] : [0]) {
                    schritte.append(AblaufSchritt(
                        uebung: nummer, art: art, dauerS: dauer, wiederholungen: wdh,
                        satz: satz, saetze: saetze, seite: seite == 0 ? nil : seite
                    ))
                }
            }
        }
        return Ablauf(
            planSessionId: einheit.id, sport: einheit.sport, titel: einheit.title,
            quelle: "entwicklung", uebungen: ablaufUebungen, schritte: schritte
        )
    }
}
#endif
