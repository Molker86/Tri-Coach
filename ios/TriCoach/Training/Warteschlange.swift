import Foundation

/// Workouts, die noch nicht in Garmin angekommen sind — auf dem Telefon abgelegt.
///
/// Im Keller oder im Studio ist das WLAN oft weg, und ein absolviertes Workout
/// darf daran nicht verloren gehen. Der Bericht bleibt hier, bis das Add-on
/// ihn als hochgeladen quittiert; die App schickt ihn beim nächsten Laden
/// erneut. Doppelt kommt dabei nichts an: Das Add-on erkennt denselben Bericht
/// an seiner `kennung`.
enum Warteschlange {
    struct Eintrag: Codable, Hashable {
        let einheitID: Int
        let bericht: TrainingsBericht
        var versuche: Int
        var letzteMeldung: String?
    }

    /// Nach so vielen Tagen gibt die App auf — dann liegt es nicht mehr am Netz.
    static let aufbewahrungTage = 14

    private static var datei: URL {
        let ordner = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
        return ordner.appendingPathComponent("offene-trainings.json")
    }

    private static let kodierer: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    private static let dekodierer: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    static func alle() -> [Eintrag] {
        guard let daten = try? Data(contentsOf: datei),
              let eintraege = try? dekodierer.decode([Eintrag].self, from: daten)
        else { return [] }
        let grenze = Date().addingTimeInterval(-Double(aufbewahrungTage) * 86_400)
        return eintraege.filter { $0.bericht.ende > grenze }
    }

    static func merken(einheitID: Int, bericht: TrainingsBericht, meldung: String?) {
        var eintraege = alle()
        if let i = eintraege.firstIndex(where: { $0.bericht.kennung == bericht.kennung }) {
            eintraege[i].versuche += 1
            eintraege[i].letzteMeldung = meldung
        } else {
            eintraege.append(Eintrag(einheitID: einheitID, bericht: bericht, versuche: 1, letzteMeldung: meldung))
        }
        speichern(eintraege)
    }

    static func vergessen(_ kennung: String) {
        speichern(alle().filter { $0.bericht.kennung != kennung })
    }

    private static func speichern(_ eintraege: [Eintrag]) {
        guard let daten = try? kodierer.encode(eintraege) else { return }
        try? daten.write(to: datei, options: .atomic)
    }
}
