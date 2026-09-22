import Foundation
import simd

/// Eine Pose: Gelenkwinkel in Grad und Beckenlage in Metern, wie sie das
/// Backend schreibt („huefte_beugen_l“: 52). Fehlende Werte sind 0 — außer
/// der Beckenhöhe (`Koerper.vorgaben`).
typealias Pose = [String: Double]
typealias Punkt = SIMD3<Double>

/// Das Körpermodell der Übungsanimationen — Zahl für Zahl dasselbe wie
/// `backend/app/animation/koerper.py`.
///
/// Der Löser im Backend hat jede Pose für **dieses** Modell gerechnet: dass die
/// Ferse aufliegt und die Hand am Knöchel ist, stimmt nur, solange Maße,
/// Achsen und Reihenfolge der Drehungen hier dieselben sind. Weicht die App
/// ab, schweben Hände über der Matte. Deshalb prüft der Simulator-Debug-Build
/// beim Start gegen `backend/tests/fixtures/animation_fk_referenz.json` —
/// dieselbe Datei, gegen die `test_animation.py` die Python-Seite prüft.
///
/// Koordinaten: x nach links der Figur, y nach oben, z nach vorn, Boden bei
/// y = 0.
enum Koerper {
    enum Mass {
        static let beckenBreite = 0.10
        static let wirbel = 0.46
        static let hals = 0.10
        static let kopf = 0.115
        static let schulterBreite = 0.19
        static let oberarm = 0.29
        static let unterarm = 0.26
        static let hand = 0.08
        static let oberschenkel = 0.44
        static let unterschenkel = 0.43
        static let fuss = 0.19
    }

    /// Ohne Angabe steht das Becken auf Standhöhe — die Sohlen genau auf dem Boden.
    static let vorgaben: Pose = ["y": 0.973]

    struct Segment {
        let von: String
        let nach: String
        let radius: Double
        /// Die Muskelgruppe, die eine Animation unter `betont` hervorheben kann.
        let gruppe: String

        /// `l`/`r`, wenn beide Enden auf derselben Seite liegen.
        var seite: String? {
            guard let a = von.last, von.dropLast().hasSuffix("_"), nach.hasSuffix("_\(a)"), a == "l" || a == "r" else {
                return nil
            }
            return String(a)
        }
    }

    static let segmente: [Segment] = {
        var liste = [
            Segment(von: "becken", nach: "taille", radius: 0.112, gruppe: "rumpf"),
            Segment(von: "taille", nach: "brust", radius: 0.128, gruppe: "rumpf"),
            Segment(von: "schulter_l", nach: "schulter_r", radius: 0.062, gruppe: "schultern"),
            Segment(von: "huefte_l", nach: "huefte_r", radius: 0.088, gruppe: "huefte"),
            Segment(von: "gesaess_l", nach: "gesaess_r", radius: 0.07, gruppe: "gesaess"),
            Segment(von: "brust", nach: "nacken", radius: 0.05, gruppe: "hals"),
        ]
        for s in ["l", "r"] {
            liste += [
                Segment(von: "schulter_\(s)", nach: "ellbogen_\(s)", radius: 0.047, gruppe: "arme"),
                Segment(von: "ellbogen_\(s)", nach: "hand_\(s)", radius: 0.039, gruppe: "arme"),
                Segment(von: "hand_\(s)", nach: "finger_\(s)", radius: 0.033, gruppe: "arme"),
                Segment(von: "huefte_\(s)", nach: "knie_\(s)", radius: 0.078, gruppe: "oberschenkel"),
                Segment(von: "knie_\(s)", nach: "knoechel_\(s)", radius: 0.056, gruppe: "waden"),
                Segment(von: "ferse_\(s)", nach: "zehen_\(s)", radius: 0.038, gruppe: "fuesse"),
            ]
        }
        return liste
    }()

    static let kopfRadius = 0.115
    static let naseRadius = 0.028

    static func wert(_ pose: Pose, _ schluessel: String) -> Double {
        pose[schluessel] ?? vorgaben[schluessel] ?? 0
    }

    // MARK: - Vorwärtskinematik

    /// Alle Gelenkpunkte einer Pose.
    static func punkte(_ pose: Pose) -> [String: Punkt] {
        let g = { (k: String) in Koerper.wert(pose, k) }
        let r0 = ry(g("gieren")) * rx(g("nicken")) * rz(g("rollen")) * ry(g("drehen"))
        let becken = Punkt(g("x"), g("y"), g("z"))
        var p: [String: Punkt] = ["becken": becken]
        p.reserveCapacity(27)

        // Die Wirbelsäule in zwei Abschnitten, jeder mit der halben Bewegung —
        // aus einem Katzenbuckel wird so ein Bogen.
        func abschnitt(_ r: simd_double3x3) -> simd_double3x3 {
            r * rz(-g("rumpf_seit") / 2) * rx(g("rumpf_beugen") / 2) * ry(g("rumpf_drehen") / 2)
        }
        let rl = abschnitt(r0)
        let taille = becken + rl * Punkt(0, Mass.wirbel * 0.45, 0)
        let rw = abschnitt(rl)
        let brust = taille + rw * Punkt(0, Mass.wirbel * 0.55, 0)
        let rk = rw * rx(g("kopf_beugen"))
        let nacken = brust + rk * Punkt(0, Mass.hals, 0)
        let kopf = nacken + rk * Punkt(0, Mass.kopf * 0.9, 0.01)
        p["taille"] = taille
        p["brust"] = brust
        p["nacken"] = nacken
        p["kopf"] = kopf
        p["nase"] = kopf + rk * Punkt(0, -0.01, Mass.kopf * 0.95)

        for (seite, s) in [("l", 1.0), ("r", -1.0)] {
            let schulter = brust + rw * Punkt(s * Mass.schulterBreite, -0.03, 0)
            let rs = rw * gelenk(
                -g("schulter_beugen_\(seite)"), g("schulter_abspreizen_\(seite)"), g("schulter_drehen_\(seite)"), s
            )
            let ellbogen = schulter + rs * Punkt(0, -Mass.oberarm, 0)
            let re = rs * rx(-g("ellbogen_\(seite)"))
            let hand = ellbogen + re * Punkt(0, -Mass.unterarm, 0)
            let finger = hand + (re * rx(g("handgelenk_\(seite)"))) * Punkt(0, -Mass.hand, 0)

            let huefte = becken + r0 * Punkt(s * Mass.beckenBreite, -0.02, 0)
            let gesaess = becken + r0 * Punkt(s * 0.07, -0.06, -0.042)
            let rh = r0 * gelenk(
                -g("huefte_beugen_\(seite)"), g("huefte_abspreizen_\(seite)"), g("huefte_drehen_\(seite)"), s
            )
            let knie = huefte + rh * Punkt(0, -Mass.oberschenkel, 0)
            let rkn = rh * rx(g("knie_\(seite)"))
            let knoechel = knie + rkn * Punkt(0, -Mass.unterschenkel, 0)
            let rf = rkn * rx(-g("fuss_\(seite)"))

            p["schulter_\(seite)"] = schulter
            p["ellbogen_\(seite)"] = ellbogen
            p["hand_\(seite)"] = hand
            p["finger_\(seite)"] = finger
            p["huefte_\(seite)"] = huefte
            p["gesaess_\(seite)"] = gesaess
            p["knie_\(seite)"] = knie
            p["knoechel_\(seite)"] = knoechel
            p["zehen_\(seite)"] = knoechel + rf * Punkt(0, -0.045, Mass.fuss)
            p["ferse_\(seite)"] = knoechel + rf * Punkt(0, -0.045, -0.04)
        }
        return p
    }

    // MARK: - Drehungen (Zeilen wie in Python, damit der Vergleich leicht fällt)

    private static func bogen(_ grad: Double) -> Double { grad * .pi / 180 }

    private static func rx(_ grad: Double) -> simd_double3x3 {
        let c = cos(bogen(grad)), s = sin(bogen(grad))
        return simd_double3x3(rows: [Punkt(1, 0, 0), Punkt(0, c, -s), Punkt(0, s, c)])
    }

    private static func ry(_ grad: Double) -> simd_double3x3 {
        let c = cos(bogen(grad)), s = sin(bogen(grad))
        return simd_double3x3(rows: [Punkt(c, 0, s), Punkt(0, 1, 0), Punkt(-s, 0, c)])
    }

    private static func rz(_ grad: Double) -> simd_double3x3 {
        let c = cos(bogen(grad)), s = sin(bogen(grad))
        return simd_double3x3(rows: [Punkt(c, -s, 0), Punkt(s, c, 0), Punkt(0, 0, 1)])
    }

    /// Drehung um eine beliebige Achse (Rodrigues).
    private static func achseWinkel(_ achse: Punkt, _ grad: Double) -> simd_double3x3 {
        let laenge = simd_length(achse)
        guard laenge >= 1e-12, abs(grad) >= 1e-12 else { return matrix_identity_double3x3 }
        let a = achse / laenge
        let (x, y, z) = (a.x, a.y, a.z)
        let c = cos(bogen(grad)), s = sin(bogen(grad)), k = 1 - c
        return simd_double3x3(rows: [
            Punkt(c + x * x * k, x * y * k - z * s, x * z * k + y * s),
            Punkt(y * x * k + z * s, c + y * y * k, y * z * k - x * s),
            Punkt(z * x * k - y * s, z * y * k + x * s, c + z * z * k),
        ])
    }

    /// Kugelgelenk: Schwenk aus Beugen und Abspreizen **gemeinsam**, dann die
    /// Drehung um die Längsachse. Warum kein Euler-Winkel: siehe `_gelenk` in
    /// `koerper.py` und „Kugelgelenke sind Schwenkvektoren“ in
    /// `docs/animationen.md`.
    private static func gelenk(_ beugen: Double, _ abspreizen: Double, _ drehen: Double, _ seite: Double) -> simd_double3x3 {
        achseWinkel(Punkt(beugen, 0, seite * abspreizen), (beugen * beugen + abspreizen * abspreizen).squareRoot())
            * ry(seite * drehen)
    }
}

// MARK: - Abspielen

extension Koerper {
    /// Linear zwischen zwei Posen; was nur eine nennt, kommt aus den Vorgaben.
    static func zwischen(_ a: Pose, _ b: Pose, _ t: Double) -> Pose {
        var ergebnis = Pose(minimumCapacity: a.count + b.count)
        for k in Set(a.keys).union(b.keys) {
            let va = wert(a, k)
            ergebnis[k] = va + (wert(b, k) - va) * t
        }
        return ergebnis
    }

    /// Weich an- und auslaufen — über den **ganzen** Übergang, nicht je Teilstück.
    static func glatt(_ t: Double) -> Double { 0.5 - 0.5 * cos(.pi * t) }
}

extension Bewegung {
    /// Wie lange eine Schleife dauert.
    var dauer: Double { max(0.1, ablauf.reduce(0) { $0 + $1.haltenS + $1.uebergangS }) }

    /// Die Pose zum Zeitpunkt `t` (Sekunden, beliebig groß — die Schleife wiederholt sich).
    ///
    /// Übergänge laufen über die gelösten Zwischenbilder des Backends, sonst
    /// rutschte ein stehender Fuß beim Überblenden über den Boden.
    func pose(bei zeit: Double) -> Pose {
        guard let erstes = ablauf.first else { return [:] }
        var t = zeit.truncatingRemainder(dividingBy: dauer)
        if t < 0 { t += dauer }
        for (i, bild) in ablauf.enumerated() {
            if t < bild.haltenS { return bild.pose }
            t -= bild.haltenS
            if t < bild.uebergangS {
                let naechste = ablauf[(i + 1) % ablauf.count].pose
                return Self.uebergang(bild, naechste, t / bild.uebergangS)
            }
            t -= bild.uebergangS
        }
        return erstes.pose
    }

    static func uebergang(_ bild: Schluesselbild, _ naechste: Pose, _ t: Double) -> Pose {
        let kette = [bild.pose] + bild.zwischen + [naechste]
        let e = Koerper.glatt(t) * Double(kette.count - 1)
        let i = min(Int(e), kette.count - 2)
        return Koerper.zwischen(kette[i], kette[i + 1], e - Double(i))
    }
}

// MARK: - Prüfung gegen die Referenz

#if DEBUG && targetEnvironment(simulator)
extension Koerper {
    private struct Referenz: Decodable {
        struct Eintrag: Decodable {
            let pose: Pose
            let punkte: [String: [Double]]
        }
        let posen: [Eintrag]
    }

    /// Rechnet die Referenzposen des Backends nach und schreibt die größte
    /// Abweichung ins Diagnoseprotokoll. Über einem Zehntelmillimeter ist das
    /// Modell auseinandergelaufen.
    static func pruefeReferenz() {
        let datei = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // Animation
            .deletingLastPathComponent()  // TriCoach
            .deletingLastPathComponent()  // ios
            .deletingLastPathComponent()  // Repo
            .appendingPathComponent("backend/tests/fixtures/animation_fk_referenz.json")
        guard let daten = try? Data(contentsOf: datei),
              let referenz = try? JSONDecoder().decode(Referenz.self, from: daten)
        else {
            protokolliere("Körpermodell: Referenz nicht lesbar (\(datei.path))")
            return
        }
        var groesste = 0.0
        var wo = ""
        for eintrag in referenz.posen {
            let ist = punkte(eintrag.pose)
            for (gelenk, soll) in eintrag.punkte {
                guard let p = ist[gelenk], soll.count == 3 else {
                    groesste = .infinity
                    wo = "\(gelenk) fehlt"
                    continue
                }
                let abweichung = simd_length(p - Punkt(soll[0], soll[1], soll[2]))
                if abweichung > groesste {
                    groesste = abweichung
                    wo = gelenk
                }
            }
        }
        let urteil = groesste < 1e-4 ? "stimmt" : "WEICHT AB"
        protokolliere(
            "Körpermodell \(urteil): \(referenz.posen.count) Referenzposen, größte Abweichung "
                + String(format: "%.2e", groesste) + " m (\(wo))"
        )
    }
}
#endif
