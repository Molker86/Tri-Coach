import Foundation

enum Datum {
    static let deutsch = Locale(identifier: "de_DE")

    static let kalender: Calendar = {
        var k = Calendar(identifier: .gregorian)
        k.locale = Locale(identifier: "de_DE")
        k.firstWeekday = 2
        k.minimumDaysInFirstWeek = 4
        return k
    }()

    private static let iso: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    static let wochentagsKuerzel = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    /// `yyyy-MM-dd` — der Schlüssel, unter dem Einheiten und Ernährungstage liegen.
    static func schluessel(_ datum: Date) -> String { iso.string(from: datum) }

    static func datum(_ text: String) -> Date? { iso.date(from: String(text.prefix(10))) }

    static func monatsanfang(_ datum: Date) -> Date {
        kalender.date(from: kalender.dateComponents([.year, .month], from: datum)) ?? datum
    }

    /// Die Zellen eines Monatsblatts ab Montag; `nil` füllt die Lücken vor dem Ersten.
    static func zellen(fuer monat: Date) -> [Date?] {
        let erster = monatsanfang(monat)
        guard let tage = kalender.range(of: .day, in: .month, for: erster) else { return [] }
        let versatz = (kalender.component(.weekday, from: erster) - kalender.firstWeekday + 7) % 7
        var zellen: [Date?] = Array(repeating: nil, count: versatz)
        for tag in tage {
            zellen.append(kalender.date(byAdding: .day, value: tag - 1, to: erster))
        }
        return zellen
    }

    /// „Montag, 21. September"
    static func lang(_ datum: Date) -> String {
        datum.formatted(.dateTime.weekday(.wide).day().month(.wide).locale(deutsch))
    }

    static func lang(_ text: String) -> String {
        datum(text).map { lang($0) } ?? text
    }

    /// „Mo, 21.09."
    static func mittel(_ text: String) -> String {
        guard let d = datum(text) else { return text }
        return d.formatted(.dateTime.weekday(.abbreviated).day(.twoDigits).month(.twoDigits).locale(deutsch))
    }

    /// „21.09."
    static func kurz(_ text: String) -> String {
        guard let d = datum(text) else { return text }
        return d.formatted(.dateTime.day(.twoDigits).month(.twoDigits).locale(deutsch))
    }

    static func zeitraum(_ von: String, _ bis: String) -> String {
        "\(kurz(von)) – \(kurz(bis))"
    }

    static func monatstitel(_ datum: Date) -> String {
        datum.formatted(.dateTime.month(.wide).year().locale(deutsch))
    }

    static func istHeute(_ text: String) -> Bool {
        text.prefix(10) == schluessel(Date())
    }

    /// Zeitstempel der API (UTC mit Zone) in Ortszeit: „21.09., 07:12"
    static func zeitstempel(_ text: String) -> String {
        let mitBruch = ISO8601DateFormatter()
        mitBruch.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let ohneBruch = ISO8601DateFormatter()
        guard let d = mitBruch.date(from: text) ?? ohneBruch.date(from: text) else { return text }
        return d.formatted(.dateTime.day(.twoDigits).month(.twoDigits).hour().minute().locale(deutsch))
    }
}

enum Zahl {
    static func ganz(_ wert: Double?) -> String? {
        guard let wert else { return nil }
        return wert.formatted(.number.precision(.fractionLength(0)).locale(Datum.deutsch))
    }

    static func kurz(_ wert: Double?, stellen: Int = 1) -> String? {
        guard let wert else { return nil }
        return wert.formatted(.number.precision(.fractionLength(0...stellen)).locale(Datum.deutsch))
    }

    static func dauer(_ minuten: Double?) -> String? {
        guard let minuten, minuten > 0 else { return nil }
        let m = Int(minuten.rounded())
        if m < 60 { return "\(m) min" }
        let rest = m % 60
        return rest == 0 ? "\(m / 60) h" : "\(m / 60) h \(rest) min"
    }

    static func distanz(_ km: Double?) -> String? {
        guard let km, km > 0 else { return nil }
        if km < 1 { return "\(Int((km * 1000).rounded())) m" }
        return "\(kurz(km, stellen: 1) ?? "") km"
    }

    static func menge(_ zutat: Zutat) -> String {
        let teile = [kurz(zutat.menge, stellen: 1), zutat.einheit].compactMap { $0 }.filter { !$0.isEmpty }
        return teile.joined(separator: " ")
    }

    static func pace(_ roh: String?, _ sportart: Sportart) -> String? {
        guard let roh, !roh.isEmpty else { return nil }
        let wert = sportart == .bike ? roh.replacingOccurrences(of: ".", with: ",") : roh
        return [wert, sportart.paceEinheit].compactMap { $0 }.joined(separator: " ")
    }

    static func makros(kh: Double?, protein: Double?, fett: Double?) -> String {
        [
            kh.flatMap { ganz($0) }.map { "KH \($0) g" },
            protein.flatMap { ganz($0) }.map { "P \($0) g" },
            fett.flatMap { ganz($0) }.map { "F \($0) g" },
        ]
        .compactMap { $0 }
        .joined(separator: " · ")
    }
}

extension Bundle {
    var versionsText: String {
        let version = infoDictionary?["CFBundleShortVersionString"] as? String ?? "–"
        let build = infoDictionary?["CFBundleVersion"] as? String ?? "–"
        return "\(version) (\(build))"
    }
}
