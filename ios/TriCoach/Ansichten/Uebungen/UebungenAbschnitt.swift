import SwiftUI

/// Die Übungen einer Kraft- oder Mobility-Einheit, jede mit laufender Vorschau.
/// Ein Tippen öffnet die Übung groß.
struct UebungenAbschnitt: View {
    let einheit: PlanEinheit

    @Environment(AppZustand.self) private var app
    @State private var modell: UebungenModell
    @State private var geoeffnet: Int?

    init(einheit: PlanEinheit) {
        self.einheit = einheit
        _modell = State(initialValue: UebungenModell(einheit: einheit))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AbschnittTitel("Übungen", symbol: "figure.strengthtraining.functional")

            if let fehler = modell.fehler {
                FehlerBanner(text: fehler)
            }

            if !modell.geladen {
                if modell.laedt {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding()
                }
            } else if modell.uebungen.isEmpty {
                HinweisKarte(
                    symbol: "figure.cooldown",
                    titel: "Keine Übungen erkannt",
                    text: "Im Aufbau dieser Einheit steht keine Übung mit englischem Namen in Klammern — dazu gibt es keine Animation."
                )
            }

            ForEach(Array(modell.uebungen.enumerated()), id: \.offset) { index, uebung in
                Button {
                    geoeffnet = index
                } label: {
                    UebungZeile(uebung: uebung, wirdErstellt: modell.lauf?.laeuft == true)
                }
                .buttonStyle(.plain)
                .disabled(uebung.animation == nil)
            }

            if modell.geladen, modell.fehlend > 0 {
                ErzeugungsKarte(modell: modell)
            }
        }
        .task(id: einheit.id) {
            await modell.laden(app)
            #if DEBUG && targetEnvironment(simulator)
            await oeffneFuerEntwicklung()
            #endif
        }
        .navigationDestination(item: $geoeffnet) { index in
            UebungView(modell: modell, index: index)
        }
    }

    #if DEBUG && targetEnvironment(simulator)
    /// `start_uebung` in `ios/Lokal/zugang.json` öffnet eine Übung von selbst
    /// („*“ = die erste mit Animation) — einmal je Start.
    private func oeffneFuerEntwicklung() async {
        guard !Entwicklungsstart.uebungGeoeffnet, let ziel = Entwicklungszugang.laden()?.startUebung else { return }
        // Erst, wenn das Einblenden der Einheit vorbei ist — ein zweiter
        // Schritt mitten im ersten geht sonst verloren.
        try? await Task.sleep(for: .seconds(1.2))
        let index = modell.uebungen.firstIndex { u in
            u.animation != nil && (ziel == "*" || u.schluessel == ziel || u.animation?.schluessel == ziel)
        }
        guard let index else { return }
        Entwicklungsstart.uebungGeoeffnet = true
        protokolliere("Öffne Übung \(modell.uebungen[index].schluessel) für die Entwicklung")
        geoeffnet = index
    }
    #endif
}

private struct UebungZeile: View {
    let uebung: EinheitUebung
    let wirdErstellt: Bool

    var body: some View {
        HStack(spacing: 12) {
            Group {
                if let animation = uebung.animation {
                    FigurAnimation(bewegung: animation.bewegung, bilderJeSekunde: 20)
                } else {
                    ZStack {
                        Color(.tertiarySystemFill)
                        Image(systemName: wirdErstellt ? "hourglass" : "figure.stand")
                            .font(.title2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .frame(width: 96, height: 72)
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

            VStack(alignment: .leading, spacing: 3) {
                Text(uebung.titel)
                    .font(.subheadline.weight(.semibold))
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                if let englisch = uebung.nameEn {
                    Text(englisch)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                zustand
            }
            Spacer(minLength: 0)
            if uebung.animation != nil {
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tertiary)
            }
        }
        .karte()
        .contentShape(Rectangle())
    }

    @ViewBuilder private var zustand: some View {
        if let animation = uebung.animation {
            if animation.istUngeprueft {
                Label("ungeprüft", systemImage: "exclamationmark.circle.fill")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.orange)
            }
        } else {
            Text(wirdErstellt ? "Animation wird erstellt …" : "Noch keine Animation")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}

/// Was fehlt, woran es zuletzt lag, und der Knopf, es jetzt zu versuchen.
private struct ErzeugungsKarte: View {
    let modell: UebungenModell

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let lauf = modell.lauf, lauf.laeuft {
                HStack(spacing: 10) {
                    ProgressView()
                    Text(lauf.message ?? "Claude beschreibt die Übungen …")
                        .font(.subheadline)
                }
                ProgressView(value: Double(lauf.progressPct), total: 100)
                Text("Das dauert einige Minuten. Die Seite aktualisiert sich von selbst.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text(
                    modell.fehlend == 1
                        ? "Für eine Übung gibt es noch keine Animation."
                        : "Für \(modell.fehlend) Übungen gibt es noch keine Animation."
                )
                .font(.subheadline.weight(.semibold))
                if let lauf = modell.lauf, lauf.gescheitert, let text = lauf.message, !text.isEmpty {
                    Text("Letzter Versuch: \(text)")
                        .font(.caption)
                        .foregroundStyle(.red)
                }
                Text("Tri-Coach lässt sie von Claude erstellen, sobald ein Claude-Zugang eingerichtet ist — von selbst, oder jetzt über den Knopf.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Button {
                    Task { await modell.erzeugen() }
                } label: {
                    Label("Jetzt erstellen", systemImage: "wand.and.stars")
                }
                .buttonStyle(.borderedProminent)
                .disabled(modell.startetLauf)
            }
        }
        .karte()
    }
}
