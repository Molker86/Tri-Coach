#if DEBUG && targetEnvironment(simulator)
import UIKit

/// Nur im Simulator-Debug-Build: legt alle drei Sekunden ein Bild des
/// eigenen Bildschirms nach `ios/build/diagnose/bildschirm.jpg`. Damit lässt
/// sich der Zustand der App auch dann prüfen, wenn das Simulator-Fenster
/// selbst nicht einsehbar ist. Bleibt das Bild stehen, hängt der Hauptthread.
enum Bildschirmfoto {
    @MainActor private static var beobachtet = Set<ObjectIdentifier>()

    @MainActor
    static func laufen() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(3))
            speichern()
        }
    }

    @MainActor
    private static func speichern() {
        let szenen = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        guard let fenster = szenen.flatMap(\.windows).first(where: \.isKeyWindow)
                ?? szenen.first?.windows.first
        else { return }
        if !beobachtet.contains(ObjectIdentifier(fenster)) {
            beobachtet.insert(ObjectIdentifier(fenster))
            let erkenner = UITapGestureRecognizer(target: Beruehrung.shared, action: #selector(Beruehrung.getippt(_:)))
            erkenner.cancelsTouchesInView = false
            erkenner.delaysTouchesEnded = false
            erkenner.delegate = Beruehrung.shared
            fenster.addGestureRecognizer(erkenner)
            protokolliere("Fenster: \(szenen.count) Szene(n), \(szenen.flatMap(\.windows).count) Fenster, beobachte \(type(of: fenster))")
        }
        let bild = UIGraphicsImageRenderer(bounds: fenster.bounds).image { _ in
            fenster.drawHierarchy(in: fenster.bounds, afterScreenUpdates: false)
        }
        guard let daten = bild.jpegData(compressionQuality: 0.7) else { return }
        try? daten.write(to: Diagnose.ordner.appendingPathComponent("bildschirm.jpg"))
    }
}
/// Meldet jede Berührung, ohne sie abzufangen.
final class Beruehrung: NSObject, UIGestureRecognizerDelegate {
    static let shared = Beruehrung()

    @objc func getippt(_ erkenner: UITapGestureRecognizer) {
        let punkt = erkenner.location(in: erkenner.view)
        protokolliere("Tippen bei (\(Int(punkt.x)), \(Int(punkt.y)))")
    }

    func gestureRecognizer(_ g: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
        true
    }
}
#endif
