import SwiftUI
import simd

/// Spielt eine Bewegung als Strichfigur ab — endlos, im Stil der Vorschaubilder
/// aus dem Backend (Matte, weicher Schatten, nahe Seite dunkel, ferne hell,
/// betonte Muskeln in Akzentfarbe).
///
/// Gezeichnet wird mit `Canvas` in einer `TimelineView`: Je Bild ist das die
/// Vorwärtskinematik für 27 Punkte und rund 25 Linien — billig genug, dass auch
/// eine Liste mit zehn laufenden Vorschauen flüssig bleibt.
struct FigurAnimation: View {
    let bewegung: Bewegung
    var laeuft: Bool = true
    /// Bildrate — die Vorschauen in der Liste kommen mit weniger aus.
    var bilderJeSekunde: Double = 30

    @Environment(\.colorScheme) private var schema
    @State private var szene: Szene
    @State private var start = Date()
    @State private var angehaltenBei: Double?

    init(bewegung: Bewegung, laeuft: Bool = true, bilderJeSekunde: Double = 30) {
        self.bewegung = bewegung
        self.laeuft = laeuft
        self.bilderJeSekunde = bilderJeSekunde
        _szene = State(initialValue: Szene(bewegung))
    }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / bilderJeSekunde, paused: !laeuft)) { kontext in
            let zeit = angehaltenBei ?? kontext.date.timeIntervalSince(start)
            Canvas { ctx, groesse in
                szene.zeichne(bewegung.pose(bei: zeit), in: &ctx, groesse: groesse, farben: Farben(schema))
            }
        }
        .onChange(of: laeuft) { _, weiter in
            // Anhalten friert das aktuelle Bild ein, statt zum Anfang zu springen.
            if weiter, let bei = angehaltenBei {
                start = Date().addingTimeInterval(-bei)
                angehaltenBei = nil
            } else if !weiter {
                angehaltenBei = Date().timeIntervalSince(start)
            }
        }
        .onChange(of: bewegung) { _, neu in szene = Szene(neu) }
        .accessibilityHidden(true)
    }
}

/// Ein einzelnes, stehendes Bild — für Stellen, an denen nichts laufen soll.
struct FigurStandbild: View {
    let bewegung: Bewegung
    var bild: Int = 0

    @Environment(\.colorScheme) private var schema

    var body: some View {
        let szene = Szene(bewegung)
        let pose = bewegung.ablauf.indices.contains(bild) ? bewegung.ablauf[bild].pose : bewegung.pose(bei: 0)
        Canvas { ctx, groesse in
            szene.zeichne(pose, in: &ctx, groesse: groesse, farben: Farben(schema))
        }
        .accessibilityHidden(true)
    }
}

// MARK: - Farben

struct Farben {
    let hintergrund: Color
    let nah: Color
    let rumpf: Color
    let fern: Color
    let akzent: Color
    let akzentFern: Color
    let matte: Color
    let requisit: Color
    let requisitKante: Color
    let requisitOben: Color
    let schatten: Color

    init(_ schema: ColorScheme) {
        func rgb(_ r: Double, _ g: Double, _ b: Double) -> Color { Color(red: r / 255, green: g / 255, blue: b / 255) }
        if schema == .dark {
            hintergrund = rgb(28, 30, 35)
            nah = rgb(226, 231, 237)
            rumpf = rgb(196, 204, 214)
            fern = rgb(106, 116, 130)
            akzent = rgb(46, 196, 182)
            akzentFern = rgb(37, 113, 108)
            matte = rgb(33, 61, 59)
            requisit = rgb(58, 64, 72)
            requisitKante = rgb(84, 92, 102)
            requisitOben = rgb(72, 79, 88)
            schatten = .black
        } else {
            hintergrund = rgb(246, 247, 249)
            nah = rgb(44, 56, 72)
            rumpf = rgb(58, 71, 88)
            fern = rgb(150, 161, 175)
            akzent = rgb(13, 125, 120)
            // Wie im Backend: die Akzentfarbe zu 45 % in den Hintergrund gemischt.
            akzentFern = rgb(118, 180, 178)
            matte = rgb(214, 234, 232)
            requisit = rgb(205, 211, 218)
            requisitKante = rgb(175, 183, 192)
            requisitOben = rgb(222, 227, 232)
            schatten = rgb(120, 134, 142)
        }
    }
}

// MARK: - Kamera und Bildausschnitt

/// Was je Bewegung einmal feststeht: Blickrichtung, Ausschnitt, Matte.
///
/// Der Ausschnitt umfasst **alle** Posen der Schleife, nicht nur die aktuelle —
/// sonst zoomte das Bild mit jeder Bewegung mit.
struct Szene {
    private let rechts: Punkt
    private let oben: Punkt
    private let zurKamera: Punkt
    private let betont: Set<String>
    private let unterlage: String
    private let requisiten: [Bewegung.Requisit]
    /// Ausschnitt in Kamerakoordinaten: x0, x1, y0, y1.
    private let ausschnitt: (Double, Double, Double, Double)
    /// Die Matte am Boden: x0, x1, z0, z1.
    private let matte: (Double, Double, Double, Double)

    init(_ bewegung: Bewegung) {
        let a = bewegung.ansicht.gieren * .pi / 180
        let b = bewegung.ansicht.neigen * .pi / 180
        let zk = Punkt(sin(a) * cos(b), sin(b), cos(a) * cos(b))
        let f = -zk
        let re = simd_normalize(Punkt(-f.z, 0, f.x))
        zurKamera = zk
        rechts = re
        oben = simd_cross(re, f)
        betont = Set(bewegung.betont)
        unterlage = bewegung.unterlage
        requisiten = bewegung.requisiten

        // Schlüsselbilder, ihre Zwischenbilder und je drei Stützstellen auf
        // dem Weg zum nächsten — wie `vorschau.vorbereiten` im Backend.
        let posen = bewegung.ablauf.map(\.pose)
        var alle = posen
        for bild in bewegung.ablauf { alle += bild.zwischen }
        for i in posen.indices {
            for t in [0.25, 0.5, 0.75] {
                alle.append(Koerper.zwischen(posen[i], posen[(i + 1) % posen.count], t))
            }
        }
        let allePunkte = alle.map { Koerper.punkte($0) }

        // Matte: um alles, was dem Boden nahe kommt.
        var xs: [Double] = [], zs: [Double] = []
        for pk in allePunkte {
            for p in pk.values where p.y < 0.35 {
                xs.append(p.x)
                zs.append(p.z)
            }
        }
        if xs.isEmpty {
            for pk in allePunkte {
                for p in pk.values {
                    xs.append(p.x)
                    zs.append(p.z)
                }
            }
        }
        matte = (
            (xs.min() ?? -0.5) - 0.25, (xs.max() ?? 0.5) + 0.25,
            (zs.min() ?? -0.5) - 0.25, (zs.max() ?? 0.5) + 0.25
        )

        var kx: [Double] = [], ky: [Double] = []
        let projiziere = { (p: Punkt) in
            kx.append(simd_dot(p, re))
            ky.append(simd_dot(p, simd_cross(re, f)))
        }
        for pk in allePunkte { pk.values.forEach(projiziere) }
        for rq in bewegung.requisiten { Szene.ecken(rq).forEach(projiziere) }
        ausschnitt = (
            (kx.min() ?? -1) - 0.15, (kx.max() ?? 1) + 0.15,
            (ky.min() ?? 0) - 0.15, (ky.max() ?? 2) + 0.15
        )
    }

    private static func ecken(_ rq: Bewegung.Requisit) -> [Punkt] {
        switch rq.art {
        case "kasten":
            let x = rq.x ?? 0, z = rq.z ?? 0, b = rq.breite ?? 0.5, t = rq.tiefe ?? 0.4, h = rq.hoehe ?? 0.3
            var e: [Punkt] = []
            for dx in [-1.0, 1.0] {
                for dz in [-1.0, 1.0] {
                    for y in [0.0, h] { e.append(Punkt(x + dx * b / 2, y, z + dz * t / 2)) }
                }
            }
            return e
        case "wand":
            let z = rq.z ?? -0.3
            return [Punkt(-0.8, 0, z), Punkt(0.8, 0, z), Punkt(-0.8, 1.9, z), Punkt(0.8, 1.9, z)]
        default:
            return []
        }
    }

    /// Bildschirmpunkt und Tiefe (größer = näher an der Kamera).
    private struct Projektion {
        let massstab: Double
        let mitteX: Double, mitteY: Double
        let breite: Double, hoehe: Double
        let rechts: Punkt, oben: Punkt, zurKamera: Punkt

        func punkt(_ p: Punkt) -> CGPoint {
            CGPoint(
                x: breite / 2 + (simd_dot(p, rechts) - mitteX) * massstab,
                y: hoehe / 2 - (simd_dot(p, oben) - mitteY) * massstab
            )
        }

        func tiefe(_ p: Punkt) -> Double { simd_dot(p, zurKamera) }
    }

    // MARK: Zeichnen

    func zeichne(_ pose: Pose, in ctx: inout GraphicsContext, groesse: CGSize, farben: Farben) {
        let rand = 0.08
        let (x0, x1, y0, y1) = ausschnitt
        let w = Double(groesse.width), h = Double(groesse.height)
        guard w > 1, h > 1 else { return }
        let proj = Projektion(
            massstab: min(w * (1 - 2 * rand) / (x1 - x0), h * (1 - 2 * rand) / (y1 - y0)),
            mitteX: (x0 + x1) / 2, mitteY: (y0 + y1) / 2,
            breite: w, hoehe: h,
            rechts: rechts, oben: oben, zurKamera: zurKamera
        )
        let m = proj.massstab

        ctx.fill(Path(CGRect(origin: .zero, size: groesse)), with: .color(farben.hintergrund))

        if unterlage == "matte" {
            let (mx0, mx1, mz0, mz1) = matte
            ctx.fill(
                vieleck([Punkt(mx0, 0, mz0), Punkt(mx1, 0, mz0), Punkt(mx1, 0, mz1), Punkt(mx0, 0, mz1)], proj),
                with: .color(farben.matte)
            )
        }
        for rq in requisiten where rq.art == "wand" {
            let e = Szene.ecken(rq)
            let flaeche = vieleck([e[0], e[1], e[3], e[2]], proj)
            ctx.fill(flaeche, with: .color(farben.requisit))
            ctx.stroke(flaeche, with: .color(farben.requisitKante), lineWidth: 1)
        }

        let pk = Koerper.punkte(pose)

        // Schatten: die bodennahen Segmente senkrecht auf den Boden gelegt und
        // weichgezeichnet — je höher, desto blasser.
        ctx.drawLayer { schicht in
            schicht.addFilter(.blur(radius: 8))
            for seg in Koerper.segmente {
                guard let a = pk[seg.von], let b = pk[seg.nach] else { continue }
                let hoehe = (a.y + b.y) / 2
                guard hoehe <= 0.7 else { continue }
                var linie = Path()
                linie.move(to: proj.punkt(Punkt(a.x, 0, a.z)))
                linie.addLine(to: proj.punkt(Punkt(b.x, 0, b.z)))
                schicht.stroke(
                    linie,
                    with: .color(farben.schatten.opacity(0.37 * max(0, 1 - hoehe / 0.7))),
                    style: StrokeStyle(lineWidth: 2 * seg.radius * m, lineCap: .round)
                )
            }
        }

        // Ein Kasten steht hinter oder unter der Figur — also vor ihr gezeichnet.
        for rq in requisiten where rq.art == "kasten" {
            let e = Szene.ecken(rq)
            for fl in [[e[0], e[1], e[3], e[2]], [e[4], e[5], e[7], e[6]], [e[0], e[1], e[5], e[4]], [e[2], e[3], e[7], e[6]]] {
                let flaeche = vieleck(fl, proj)
                ctx.fill(flaeche, with: .color(farben.requisit))
                ctx.stroke(flaeche, with: .color(farben.requisitKante), lineWidth: 1)
            }
            let deckel = vieleck([e[1], e[3], e[7], e[5]], proj)
            ctx.fill(deckel, with: .color(farben.requisitOben))
            ctx.stroke(deckel, with: .color(farben.requisitKante), lineWidth: 1)
        }

        // Die Figur, von hinten nach vorn.
        let fern: String = {
            guard let l = pk["huefte_l"], let r = pk["huefte_r"] else { return "r" }
            return proj.tiefe(l) > proj.tiefe(r) ? "r" : "l"
        }()
        struct Teil {
            let tiefe: Double
            let a: Punkt
            let b: Punkt?
            let radius: Double
            let gruppe: String
            let seite: String?
            let istBecken: Bool
        }
        var teile: [Teil] = []
        teile.reserveCapacity(Koerper.segmente.count + 2)
        for seg in Koerper.segmente {
            guard let a = pk[seg.von], let b = pk[seg.nach] else { continue }
            teile.append(Teil(
                tiefe: (proj.tiefe(a) + proj.tiefe(b)) / 2, a: a, b: b, radius: seg.radius,
                gruppe: seg.gruppe, seite: seg.seite, istBecken: seg.von == "becken"
            ))
        }
        if let kopf = pk["kopf"] {
            teile.append(Teil(tiefe: proj.tiefe(kopf), a: kopf, b: nil, radius: Koerper.kopfRadius, gruppe: "kopf", seite: nil, istBecken: false))
        }
        if let nase = pk["nase"] {
            teile.append(Teil(tiefe: proj.tiefe(nase), a: nase, b: nil, radius: Koerper.naseRadius, gruppe: "kopf", seite: nil, istBecken: false))
        }
        let atmen = Koerper.wert(pose, "atmen")
        let rumpfgruppen: Set<String> = ["rumpf", "huefte", "hals", "kopf", "gesaess", "schultern"]
        let ohneKante: Set<String> = ["rumpf", "huefte", "gesaess", "schultern"]

        for teil in teile.sorted(by: { $0.tiefe < $1.tiefe }) {
            let istFern = teil.seite == fern
            let hervor = betont.contains(teil.gruppe) || (teil.seite.map { betont.contains("\(teil.gruppe)_\($0)") } ?? false)
            let farbe: Color
            if hervor {
                farbe = istFern ? farben.akzentFern : farben.akzent
            } else if rumpfgruppen.contains(teil.gruppe) {
                farbe = farben.rumpf
            } else {
                farbe = istFern ? farben.fern : farben.nah
            }
            var radius = teil.radius * m
            if teil.istBecken, atmen > 0 { radius *= 1 + 0.22 * atmen }

            let pa = proj.punkt(teil.a)
            guard let b = teil.b else {
                ctx.fill(Path(ellipseIn: CGRect(x: pa.x - radius, y: pa.y - radius, width: 2 * radius, height: 2 * radius)), with: .color(farbe))
                continue
            }
            var linie = Path()
            linie.move(to: pa)
            linie.addLine(to: proj.punkt(b))
            // Eine schmale Kante in Hintergrundfarbe trennt die nahen
            // Gliedmaßen vom Rumpf dahinter — sonst verschwimmt ein Arm vor der Brust.
            if !istFern, !ohneKante.contains(teil.gruppe) {
                ctx.stroke(linie, with: .color(farben.hintergrund), style: StrokeStyle(lineWidth: 2 * (radius + 1.4), lineCap: .round))
            }
            ctx.stroke(linie, with: .color(farbe), style: StrokeStyle(lineWidth: 2 * radius, lineCap: .round))
        }
    }

    private func vieleck(_ ecken: [Punkt], _ proj: Projektion) -> Path {
        var pfad = Path()
        pfad.addLines(ecken.map(proj.punkt))
        pfad.closeSubpath()
        return pfad
    }
}
