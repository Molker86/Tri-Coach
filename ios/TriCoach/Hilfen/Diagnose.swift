#if DEBUG && targetEnvironment(simulator)
import Foundation

/// Nur im Simulator-Debug-Build: schreibt mit, was die App lädt, nach
/// `ios/build/diagnose/` auf dem Mac (steht in `.gitignore`). Token und die
/// Antwort von `/auth/login` werden nie geschrieben.
enum Diagnose {
    static let ordner = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()  // Hilfen
        .deletingLastPathComponent()  // TriCoach
        .deletingLastPathComponent()  // ios
        .appendingPathComponent("build/diagnose", isDirectory: true)

    static func protokoll(_ zeile: String) {
        // Zusätzlich in die Xcode-Konsole — falls der Simulator das Schreiben
        // auf den Mac verweigert, ist sie die einzige Spur.
        print("[TriCoach] \(zeile)")
        try? FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
        let datei = ordner.appendingPathComponent("protokoll.txt")
        let text = "\(Date().formatted(.iso8601)) \(zeile)\n"
        if let griff = try? FileHandle(forWritingTo: datei) {
            griff.seekToEndOfFile()
            griff.write(Data(text.utf8))
            try? griff.close()
        } else {
            try? Data(text.utf8).write(to: datei)
        }
    }

    static func antwort(_ endpunkt: String, status: Int, daten: Data) {
        guard !endpunkt.hasPrefix("/auth/login") else {
            protokoll("\(endpunkt) → \(status)")
            return
        }
        try? FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
        let name = endpunkt
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "?", with: "_")
            .replacingOccurrences(of: "=", with: "-")
            .trimmingCharacters(in: CharacterSet(charactersIn: "_"))
        do {
            try daten.write(to: ordner.appendingPathComponent("\(name).json"))
        } catch {
            print("[TriCoach] Diagnose nicht schreibbar (\(ordner.path)): \(error.localizedDescription)")
        }
        protokoll("\(endpunkt) → \(status), \(daten.count) Bytes")
    }
}
#endif

/// Schreibt eine Zeile ins Diagnoseprotokoll — nur im Simulator-Debug-Build,
/// sonst ein leerer Aufruf. Niemals Token oder Sitzungskennungen übergeben.
func protokolliere(_ text: @autoclosure () -> String) {
    #if DEBUG && targetEnvironment(simulator)
    Diagnose.protokoll(text())
    #endif
}
