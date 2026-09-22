import Foundation

// Spiegeln `AnimationOut`, `EinheitUebungenOut` und `KiJobOut` aus
// `backend/app/schemas.py` und die Bewegung aus `animation/format.py`.
//
// **Mit eigenen CodingKeys statt `.convertFromSnakeCase`:** Der JSONDecoder
// wendet die Strategie auch auf die Schlüssel von Wörterbüchern an — aus
// „huefte_beugen_l“ in einer Pose würde „huefteBeugenL“, und die Figur stünde
// still in der Grundhaltung. Dekodiert wird deshalb wortgetreu
// (`TriCoachClient.wortgetreu`).

/// Die abspielbare Bewegung — fertig gelöste Posen, nichts mehr zu rechnen.
struct Bewegung: Decodable, Hashable {
    struct Ansicht: Decodable, Hashable {
        /// 0 = von vorn, 90 = von links der Figur.
        var gieren: Double = 70
        /// Wie weit die Kamera von oben schaut.
        var neigen: Double = 15

        init() {}

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            gieren = try c.decodeIfPresent(Double.self, forKey: .gieren) ?? 70
            neigen = try c.decodeIfPresent(Double.self, forKey: .neigen) ?? 15
        }

        private enum CodingKeys: String, CodingKey { case gieren, neigen }
    }

    struct Requisit: Decodable, Hashable {
        let art: String
        let x: Double?
        let z: Double?
        let breite: Double?
        let tiefe: Double?
        let hoehe: Double?
    }

    struct Schluesselbild: Decodable, Hashable {
        let pose: Pose
        let haltenS: Double
        let uebergangS: Double
        /// Gelöste Posen auf dem Weg zum nächsten Bild.
        let zwischen: [Pose]

        private enum CodingKeys: String, CodingKey {
            case pose, zwischen
            case haltenS = "halten_s"
            case uebergangS = "uebergang_s"
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            pose = try c.decode(Pose.self, forKey: .pose)
            haltenS = try c.decodeIfPresent(Double.self, forKey: .haltenS) ?? 0.4
            uebergangS = try c.decodeIfPresent(Double.self, forKey: .uebergangS) ?? 1.0
            zwischen = try c.decodeIfPresent([Pose].self, forKey: .zwischen) ?? []
        }
    }

    let ansicht: Ansicht
    let betont: [String]
    let unterlage: String
    let requisiten: [Requisit]
    let ablauf: [Schluesselbild]

    private enum CodingKeys: String, CodingKey {
        case ansicht, betont, unterlage, requisiten, ablauf
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ansicht = try c.decodeIfPresent(Ansicht.self, forKey: .ansicht) ?? Ansicht()
        betont = try c.decodeIfPresent([String].self, forKey: .betont) ?? []
        unterlage = try c.decodeIfPresent(String.self, forKey: .unterlage) ?? "matte"
        requisiten = try c.decodeIfPresent([Requisit].self, forKey: .requisiten) ?? []
        ablauf = try c.decode([Schluesselbild].self, forKey: .ablauf)
    }
}

/// Eine Animation, wie sie `/api/animationen/…` liefert.
struct UebungsAnimation: Decodable, Identifiable, Hashable {
    let schluessel: String
    let name: String
    let aliase: [String]
    /// bibliothek | ki
    let herkunft: String
    /// freigegeben | ungeprueft | verworfen
    let zustand: String
    let format: Int
    let bewegung: Bewegung
    let hinweise: [String]?
    let rueckmeldung: String?
    let modelUsed: String?
    let geaendertAm: String

    var id: String { schluessel }
    var istUngeprueft: Bool { zustand == "ungeprueft" }
    var vonKI: Bool { herkunft == "ki" }

    /// Das Format, das diese App abspielen kann. Ein neueres heißt: App aktualisieren.
    static let bekanntesFormat = 1

    private enum CodingKeys: String, CodingKey {
        case schluessel, name, aliase, herkunft, zustand, format, bewegung, hinweise, rueckmeldung
        case modelUsed = "model_used"
        case geaendertAm = "geaendert_am"
    }
}

/// Eine Übung aus dem Aufbautext einer Einheit.
struct EinheitUebung: Decodable, Hashable {
    /// Die Zeile im Wortlaut des Plans („3x12 Beckenheben (Glute Bridge)“).
    let zeile: String
    let nameEn: String?
    let schluessel: String
    let animation: UebungsAnimation?

    private enum CodingKeys: String, CodingKey {
        case zeile, schluessel, animation
        case nameEn = "name_en"
    }

    /// Die Zeile ohne die englische Klammer — die steht darunter eigens.
    var titel: String {
        guard let name = nameEn, let bereich = zeile.range(of: "(\(name))", options: .backwards) else { return zeile }
        var rest = zeile
        rest.removeSubrange(bereich)
        let bereinigt = rest.replacingOccurrences(of: "  ", with: " ").trimmingCharacters(in: .whitespaces)
        return bereinigt.isEmpty ? zeile : bereinigt
    }
}

struct EinheitUebungen: Decodable {
    let planSessionId: Int
    let uebungen: [EinheitUebung]
    let fehlend: Int
    let erzeugung: KiLauf?

    private enum CodingKeys: String, CodingKey {
        case uebungen, fehlend, erzeugung
        case planSessionId = "plan_session_id"
    }
}

/// Ein Lauf gegen die KI (`KiJobOut`) — nur, was die App davon braucht.
struct KiLauf: Decodable, Hashable {
    let id: Int
    let kind: String
    let state: String
    let progressPct: Int
    let message: String?
    let startedAt: String
    let finishedAt: String?

    var laeuft: Bool { state == "queued" || state == "running" }
    var gescheitert: Bool { state == "failed" || state == "interrupted" }

    private enum CodingKeys: String, CodingKey {
        case id, kind, state, message
        case progressPct = "progress_pct"
        case startedAt = "started_at"
        case finishedAt = "finished_at"
    }
}

/// Deutsche Namen der Muskelgruppen aus `koerper.MUSKELGRUPPEN`.
enum Muskelgruppe {
    static func name(_ roh: String) -> String {
        var gruppe = roh
        var seite = ""
        if roh.hasSuffix("_l") || roh.hasSuffix("_r") {
            seite = roh.hasSuffix("_l") ? " (links)" : " (rechts)"
            gruppe = String(roh.dropLast(2))
        }
        let namen = [
            "rumpf": "Rumpf", "schultern": "Schultern", "huefte": "Hüfte", "gesaess": "Gesäß",
            "hals": "Nacken", "arme": "Arme", "oberschenkel": "Oberschenkel", "waden": "Waden",
            "fuesse": "Füße", "kopf": "Kopf",
        ]
        return (namen[gruppe] ?? gruppe.capitalized) + seite
    }
}
