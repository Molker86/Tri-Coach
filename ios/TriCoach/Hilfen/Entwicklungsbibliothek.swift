#if DEBUG && targetEnvironment(simulator)
import Foundation

/// Nur im Simulator-Debug-Build: die Übungen einer Einheit aus der Bibliothek
/// im Repository statt vom Add-on.
///
/// Damit lassen sich Figur und Ansichten prüfen, bevor das Add-on mit den
/// Animationen (ab 4.6.0) in Home Assistant läuft — ein älteres antwortet auf
/// `/api/animationen/…` mit 404. Die Zuordnung ist eine vereinfachte
/// Nachbildung von `animation/einheit.py` (nur die Klammer, kein Bauplan);
/// maßgeblich ist immer die des Backends.
enum Entwicklungsbibliothek {
    private struct Datei: Decodable {
        let uebungen: [Eintrag]
    }

    private struct Eintrag: Decodable {
        let schluessel: String
        let name: String
        let aliase: [String]
        let bewegung: Bewegung

        private enum CodingKeys: String, CodingKey { case schluessel, name, aliase }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            schluessel = try c.decode(String.self, forKey: .schluessel)
            name = try c.decode(String.self, forKey: .name)
            aliase = try c.decodeIfPresent([String].self, forKey: .aliase) ?? []
            bewegung = try Bewegung(from: decoder)
        }
    }

    static func uebungen(fuer einheit: PlanEinheit) -> EinheitUebungen? {
        let datei = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // Hilfen
            .deletingLastPathComponent()  // TriCoach
            .deletingLastPathComponent()  // ios
            .deletingLastPathComponent()  // Repo
            .appendingPathComponent("backend/app/animation/bibliothek/bibliothek.json")
        guard let daten = try? Data(contentsOf: datei),
              let bibliothek = try? JSONDecoder().decode(Datei.self, from: daten)
        else { return nil }

        var index: [String: Eintrag] = [:]
        for e in bibliothek.uebungen {
            for name in [e.schluessel, e.name] + e.aliase where index[normalisiert(name)] == nil {
                index[normalisiert(name)] = e
            }
        }

        let trenner = try! NSRegularExpression(pattern: #"\s+/\s+|[\n;·•]|\s+\|\s+"#)
        let text = einheit.structure ?? ""
        let voll = NSRange(text.startIndex..., in: text)
        let markiert = trenner.stringByReplacingMatches(in: text, range: voll, withTemplate: "\u{1}")
        let zeilen = markiert.split(separator: "\u{1}")
            .map { $0.trimmingCharacters(in: CharacterSet(charactersIn: " .\t")) }
            .filter { !$0.isEmpty }

        var uebungen: [EinheitUebung] = []
        for zeile in zeilen {
            guard let auf = zeile.lastIndex(of: "("), let zu = zeile[auf...].firstIndex(of: ")") else { continue }
            let englisch = String(zeile[zeile.index(after: auf)..<zu]).trimmingCharacters(in: .whitespaces)
            let schluessel = normalisiert(englisch)
            guard !schluessel.isEmpty else { continue }
            let animation = index[schluessel].map { e in
                UebungsAnimation(
                    schluessel: e.schluessel, name: e.name, aliase: e.aliase, herkunft: "bibliothek",
                    zustand: "freigegeben", format: 1, bewegung: e.bewegung, hinweise: nil,
                    rueckmeldung: nil, modelUsed: nil, geaendertAm: ""
                )
            }
            uebungen.append(EinheitUebung(zeile: zeile, nameEn: englisch, schluessel: schluessel, animation: animation))
        }
        return EinheitUebungen(
            planSessionId: einheit.id,
            uebungen: uebungen,
            fehlend: uebungen.filter { $0.animation == nil }.count,
            erzeugung: nil
        )
    }

    /// Wie `animation/schluessel.normalisiert`: „Child's Pose“ → `childs-pose`.
    static func normalisiert(_ name: String) -> String {
        var text = name.lowercased()
        for (alt, neu) in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("é", "e"), ("è", "e"), ("'", ""), ("’", "")] {
            text = text.replacingOccurrences(of: alt, with: neu)
        }
        let woerter = text.split { !($0.isASCII && ($0.isLetter || $0.isNumber)) }
        return woerter.joined(separator: "-")
    }
}
#endif
