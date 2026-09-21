import SwiftUI

/// Sportarten wie im Backend (`Sport` in `frontend/src/types.ts`).
enum Sportart: String {
    case run, bike, swim, strength, mobility, brick, rest, unbekannt

    init(_ roh: String) {
        self = Sportart(rawValue: roh.lowercased()) ?? .unbekannt
    }

    var name: String {
        switch self {
        case .run: "Laufen"
        case .bike: "Radfahren"
        case .swim: "Schwimmen"
        case .strength: "Kraft"
        case .mobility: "Beweglichkeit"
        case .brick: "Koppeltraining"
        case .rest: "Ruhetag"
        case .unbekannt: "Training"
        }
    }

    var symbol: String {
        switch self {
        case .run: "figure.run"
        case .bike: "figure.outdoor.cycle"
        case .swim: "figure.pool.swim"
        case .strength: "dumbbell.fill"
        case .mobility: "figure.flexibility"
        case .brick: "arrow.triangle.2.circlepath"
        case .rest: "bed.double.fill"
        case .unbekannt: "questionmark"
        }
    }

    var farbe: Color {
        switch self {
        case .run: .orange
        case .bike: .blue
        case .swim: .cyan
        case .strength: .purple
        case .mobility: .green
        case .brick: .pink
        case .rest: .gray
        case .unbekannt: .secondary
        }
    }

    /// Einheit, in der `avg_pace` steht — das Backend schreibt nur den Wert.
    var paceEinheit: String? {
        switch self {
        case .run: "/km"
        case .swim: "/100 m"
        case .bike: "km/h"
        default: nil
        }
    }
}

/// Einheitentypen wie `SESSION_TYPE_LABEL` im Web-Frontend.
enum Einheitentyp {
    private static let namen: [String: String] = [
        "recovery": "Regeneration",
        "easy": "Locker",
        "endurance": "Grundlagenausdauer",
        "tempo": "Tempo",
        "threshold": "Schwelle",
        "vo2max": "VO2max",
        "intervals": "Intervalle",
        "long": "Lange Einheit",
        "technique": "Technik",
        "race_pace": "Wettkampftempo",
        "strength": "Kraft",
        "mobility": "Beweglichkeit",
        "brick": "Koppeltraining",
        "test": "Leistungstest",
        "rest": "Ruhe",
    ]

    static func name(_ roh: String?) -> String? {
        guard let roh, !roh.isEmpty else { return nil }
        return namen[roh.lowercased()] ?? roh.capitalized
    }
}

/// Bezug einer Mahlzeit oder Gabe zur Einheit des Tages.
enum Bezug {
    static func name(_ roh: String?) -> String? {
        switch roh?.lowercased() {
        case "vor": "vor dem Training"
        case "waehrend": "während"
        case "nach": "nach dem Training"
        default: nil
        }
    }
}
