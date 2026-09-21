import SwiftUI

extension View {
    /// Die Karte, auf der im Kalender alles liegt.
    func karte() -> some View {
        padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                Color(.secondarySystemGroupedBackground),
                in: RoundedRectangle(cornerRadius: 14, style: .continuous)
            )
    }
}

struct SportSymbol: View {
    let sportart: Sportart
    var groesse: CGFloat = 40

    var body: some View {
        Image(systemName: sportart.symbol)
            .font(.system(size: groesse * 0.45, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: groesse, height: groesse)
            .background(sportart.farbe.gradient, in: RoundedRectangle(cornerRadius: groesse * 0.28, style: .continuous))
            .accessibilityLabel(sportart.name)
    }
}

struct AbschnittTitel: View {
    let titel: String
    let symbol: String

    init(_ titel: String, symbol: String) {
        self.titel = titel
        self.symbol = symbol
    }

    var body: some View {
        Label(titel, systemImage: symbol)
            .font(.footnote.weight(.semibold))
            .foregroundStyle(.secondary)
            .textCase(.uppercase)
            .padding(.top, 6)
    }
}

struct FehlerBanner: View {
    let text: String

    var body: some View {
        Label(text, systemImage: "exclamationmark.triangle.fill")
            .font(.subheadline)
            .foregroundStyle(Color.red)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(Color.red.opacity(0.1), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

struct HinweisKarte: View {
    let symbol: String
    let titel: String
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol)
                .font(.title2)
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 4) {
                Text(titel).font(.headline)
                Text(text).font(.subheadline).foregroundStyle(.secondary)
            }
        }
        .karte()
    }
}

struct MakroLeiste: View {
    let kcal: Double?
    let kh: Double?
    let protein: Double?
    let fett: Double?

    var body: some View {
        HStack(spacing: 6) {
            MakroWert(titel: "kcal", wert: kcal, einheit: "", farbe: .orange)
            MakroWert(titel: "Kohlenh.", wert: kh, einheit: "g", farbe: .blue)
            MakroWert(titel: "Protein", wert: protein, einheit: "g", farbe: .red)
            MakroWert(titel: "Fett", wert: fett, einheit: "g", farbe: .yellow)
        }
    }
}

private struct MakroWert: View {
    let titel: String
    let wert: Double?
    let einheit: String
    let farbe: Color

    var body: some View {
        VStack(spacing: 2) {
            Text(wertText)
                .font(.callout.weight(.semibold).monospacedDigit())
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Text(titel)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
        .background(farbe.opacity(0.14), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private var wertText: String {
        guard let text = Zahl.ganz(wert) else { return "–" }
        return einheit.isEmpty ? text : "\(text) \(einheit)"
    }
}

struct Kennzahl: Hashable {
    let titel: String
    let wert: String
    let symbol: String
}

struct KennzahlKachel: View {
    let kennzahl: Kennzahl

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(kennzahl.titel, systemImage: kennzahl.symbol)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(kennzahl.wert)
                .font(.headline)
                .lineLimit(2)
                .minimumScaleFactor(0.8)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

struct TextAbschnitt: View {
    let titel: String
    let text: String?
    let symbol: String

    var body: some View {
        if let text, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Label(titel, systemImage: symbol)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(text)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .karte()
        }
    }
}

struct BezugMarke: View {
    let bezug: String?

    var body: some View {
        if let text = Bezug.name(bezug) {
            Text(text)
                .font(.caption2.weight(.semibold))
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(Color.accentColor.opacity(0.15), in: Capsule())
                .foregroundStyle(Color.accentColor)
        }
    }
}
