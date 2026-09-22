import SwiftUI

/// Das laufende Workout im Vollbild — Übung, Animation, Timer oder Zähler.
struct WorkoutView: View {
    let einheit: PlanEinheit

    @Environment(AppZustand.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var modell: WorkoutModell
    @State private var beendenFragen = false

    init(einheit: PlanEinheit) {
        self.einheit = einheit
        _modell = State(initialValue: WorkoutModell(einheit: einheit))
    }

    var body: some View {
        ZStack {
            Color(.systemGroupedBackground).ignoresSafeArea()
            switch modell.phase {
            case .laden:
                ladeAnsicht
            case .bereit:
                StartAnsicht(modell: modell, schliessen: { dismiss() })
            case .vorbereitung, .aktiv:
                LaufAnsicht(modell: modell, beenden: { beendenFragen = true })
            case .fertig:
                AbschlussAnsicht(modell: modell, schliessen: { dismiss() })
            }
        }
        .task { await modell.laden(app) }
        .onDisappear { modell.aufraeumen() }
        .confirmationDialog("Workout beenden?", isPresented: $beendenFragen, titleVisibility: .visible) {
            Button("Beenden und an Garmin senden") { modell.beenden() }
            Button("Verwerfen", role: .destructive) {
                modell.verwerfen()
                dismiss()
            }
            Button("Weitermachen", role: .cancel) {}
        } message: {
            Text("Erledigte Sätze gehen an Garmin, der laufende nicht.")
        }
    }

    @ViewBuilder private var ladeAnsicht: some View {
        VStack(spacing: 16) {
            if let fehler = modell.fehler {
                FehlerBanner(text: fehler)
                Button("Schließen") { dismiss() }
                    .buttonStyle(.bordered)
            } else {
                ProgressView("Workout wird geladen …")
            }
        }
        .padding()
    }
}

// MARK: - Vor dem Start

private struct StartAnsicht: View {
    let modell: WorkoutModell
    let schliessen: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button("Abbrechen", action: schliessen)
                Spacer()
            }
            .padding()

            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(modell.einheit.title)
                        .font(.title2.weight(.bold))
                    Text(zusammenfassung)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    ForEach(modell.ablauf?.uebungen ?? [], id: \.nummer) { uebung in
                        HStack(spacing: 12) {
                            Group {
                                if let animation = uebung.animation {
                                    FigurStandbild(bewegung: animation.bewegung, bild: min(1, animation.bewegung.ablauf.count - 1))
                                } else {
                                    Image(systemName: "figure.strengthtraining.functional")
                                        .font(.title2)
                                        .foregroundStyle(.secondary)
                                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                                        .background(Color(.tertiarySystemFill))
                                }
                            }
                            .frame(width: 64, height: 48)
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                            VStack(alignment: .leading, spacing: 2) {
                                Text(uebung.titel).font(.subheadline.weight(.semibold))
                                Text(umfang(uebung)).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 0)
                        }
                        .karte()
                    }
                }
                .padding(.horizontal)
            }

            Button { modell.starten() } label: {
                Label("Workout starten", systemImage: "play.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .padding()
        }
    }

    private var zusammenfassung: String {
        let schritte = modell.schritte
        let uebungen = modell.ablauf?.uebungen.count ?? 0
        return "\(uebungen) Übungen · \(schritte.count) Sätze" + (modell.einheit.durationMin.map { " · ca. \(Int($0)) min" } ?? "")
    }

    private func umfang(_ uebung: AblaufUebung) -> String {
        let eigene = modell.schritte.filter { $0.uebung == uebung.nummer }
        guard let erster = eigene.first else { return "" }
        let saetze = erster.saetze
        let seite = eigene.contains { $0.seite != nil } ? " je Seite" : ""
        switch erster.art {
        case .zeit: return "\(saetze) × \(Zeit.kurz(TimeInterval(erster.dauerS ?? 0)))\(seite)"
        case .wiederholungen: return "\(saetze) × \(erster.wiederholungen ?? 0) Wdh.\(seite)"
        case .taste: return saetze > 1 ? "\(saetze) Sätze\(seite)" : "bis du fertig bist"
        }
    }
}

// MARK: - Während des Workouts

private struct LaufAnsicht: View {
    let modell: WorkoutModell
    let beenden: () -> Void

    var body: some View {
        let schritt = modell.schritt
        let uebung = modell.uebung(schritt)

        VStack(spacing: 14) {
            kopfzeile

            ZStack(alignment: .topTrailing) {
                if let animation = uebung?.animation {
                    FigurAnimation(bewegung: animation.bewegung, laeuft: !modell.pausiert)
                } else {
                    Image(systemName: "figure.strengthtraining.functional")
                        .font(.system(size: 64))
                        .foregroundStyle(.tertiary)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color(.secondarySystemGroupedBackground))
                }
            }
            .aspectRatio(4 / 3, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

            VStack(spacing: 4) {
                Text(uebung?.titel ?? "Übung")
                    .font(.title2.weight(.bold))
                    .multilineTextAlignment(.center)
                if let englisch = uebung?.nameEn {
                    Text(englisch).font(.subheadline).foregroundStyle(.secondary)
                }
                if let schritt {
                    Text(satzText(schritt))
                        .font(.subheadline.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 3)
                        .background(Color.accentColor.opacity(0.15), in: Capsule())
                        .foregroundStyle(Color.accentColor)
                }
            }

            Spacer(minLength: 0)
            mitte(schritt)
            Spacer(minLength: 0)

            steuerung(schritt)
            naechsteZeile
        }
        .padding()
        .overlay {
            if modell.pausiert { pausenSchicht }
        }
    }

    private var kopfzeile: some View {
        HStack {
            Button(action: beenden) {
                Image(systemName: "xmark")
                    .font(.headline)
                    .frame(width: 40, height: 40)
                    .background(Color(.secondarySystemGroupedBackground), in: Circle())
            }
            .accessibilityLabel("Workout beenden")
            Spacer()
            VStack(spacing: 2) {
                Text(Zeit.uhr(modell.gesamtdauer))
                    .font(.headline.monospacedDigit())
                Text("Satz \(modell.index + 1) von \(modell.schritte.count)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button { modell.pauseUmschalten() } label: {
                Image(systemName: modell.pausiert ? "play.fill" : "pause.fill")
                    .font(.headline)
                    .frame(width: 40, height: 40)
                    .background(Color(.secondarySystemGroupedBackground), in: Circle())
            }
            .accessibilityLabel(modell.pausiert ? "Fortsetzen" : "Pause")
        }
        .overlay(alignment: .bottom) {
            ProgressView(value: Double(modell.index), total: Double(max(1, modell.schritte.count)))
                .offset(y: 14)
        }
        .padding(.bottom, 8)
    }

    @ViewBuilder private func mitte(_ schritt: AblaufSchritt?) -> some View {
        if modell.phase == .vorbereitung {
            VStack(spacing: 6) {
                Text("Bereit machen")
                    .font(.headline)
                    .foregroundStyle(.secondary)
                Text("\(Int((modell.verbleibend ?? 0).rounded(.up)))")
                    .font(.system(size: 72, weight: .bold, design: .rounded).monospacedDigit())
                    .contentTransition(.numericText(countsDown: true))
            }
        } else if let schritt {
            switch schritt.art {
            case .zeit:
                let dauer = TimeInterval(schritt.dauerS ?? 0)
                let rest = modell.verbleibend ?? 0
                ZStack {
                    Circle().stroke(Color.accentColor.opacity(0.15), lineWidth: 10)
                    Circle()
                        .trim(from: 0, to: dauer > 0 ? rest / dauer : 0)
                        .stroke(Color.accentColor, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                        .animation(.linear(duration: 0.2), value: rest)
                    Text(Zeit.uhr(rest.rounded(.up)))
                        .font(.system(size: 52, weight: .bold, design: .rounded).monospacedDigit())
                }
                .frame(width: 180, height: 180)
            case .wiederholungen:
                VStack(spacing: 6) {
                    HStack(spacing: 28) {
                        rundKnopf("minus") { modell.wiederholungen = max(0, modell.wiederholungen - 1) }
                        Text("\(modell.wiederholungen)")
                            .font(.system(size: 72, weight: .bold, design: .rounded).monospacedDigit())
                            .frame(minWidth: 110)
                            .contentTransition(.numericText())
                        rundKnopf("plus") { modell.wiederholungen += 1 }
                    }
                    Text("Wiederholungen · Soll \(schritt.wiederholungen ?? 0)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            case .taste:
                VStack(spacing: 6) {
                    Text(Zeit.uhr(modell.imSatz))
                        .font(.system(size: 52, weight: .bold, design: .rounded).monospacedDigit())
                    Text("Tippe auf „Weiter“, wenn du fertig bist.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private func rundKnopf(_ symbol: String, aktion: @escaping () -> Void) -> some View {
        Button(action: aktion) {
            Image(systemName: symbol)
                .font(.title2.weight(.bold))
                .frame(width: 56, height: 56)
                .background(Color(.secondarySystemGroupedBackground), in: Circle())
        }
        .buttonStyle(.plain)
    }

    private func steuerung(_ schritt: AblaufSchritt?) -> some View {
        HStack(spacing: 12) {
            Button { modell.zurueck() } label: {
                Image(systemName: "backward.end.fill")
                    .frame(width: 52, height: 52)
                    .background(Color(.secondarySystemGroupedBackground), in: Circle())
            }
            .disabled(modell.index == 0)
            .accessibilityLabel("Zurück")

            Button { modell.weiter() } label: {
                Text(hauptText(schritt))
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 16)
            }
            .buttonStyle(.borderedProminent)

            Button { modell.ueberspringen() } label: {
                Image(systemName: "forward.end.fill")
                    .frame(width: 52, height: 52)
                    .background(Color(.secondarySystemGroupedBackground), in: Circle())
            }
            .accessibilityLabel("Überspringen")
        }
        .buttonStyle(.plain)
    }

    private func hauptText(_ schritt: AblaufSchritt?) -> String {
        if modell.phase == .vorbereitung { return "Los" }
        switch schritt?.art {
        case .zeit: return "Satz fertig"
        case .wiederholungen: return "Satz fertig"
        default: return "Weiter"
        }
    }

    @ViewBuilder private var naechsteZeile: some View {
        if let naechster = modell.naechster, let uebung = modell.uebung(naechster) {
            Text("Danach: \(uebung.titel) · \(kurzUmfang(naechster))")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        } else {
            Text("Letzter Satz")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    private var pausenSchicht: some View {
        ZStack {
            Rectangle().fill(.ultraThinMaterial).ignoresSafeArea()
            VStack(spacing: 16) {
                Text("Pausiert").font(.largeTitle.weight(.bold))
                Button { modell.pauseUmschalten() } label: {
                    Label("Fortsetzen", systemImage: "play.fill")
                        .font(.headline)
                        .padding(.horizontal, 24)
                        .padding(.vertical, 10)
                }
                .buttonStyle(.borderedProminent)
                Button("Workout beenden", action: beenden)
                    .buttonStyle(.bordered)
            }
        }
    }

    private func satzText(_ schritt: AblaufSchritt) -> String {
        var text = "Satz \(schritt.satz) von \(schritt.saetze)"
        if let seite = schritt.seite { text += " · \(seite). Seite" }
        return text
    }

    private func kurzUmfang(_ schritt: AblaufSchritt) -> String {
        switch schritt.art {
        case .zeit: return Zeit.kurz(TimeInterval(schritt.dauerS ?? 0))
        case .wiederholungen: return "\(schritt.wiederholungen ?? 0) Wdh."
        case .taste: return "ohne Vorgabe"
        }
    }
}

// MARK: - Danach

private struct AbschlussAnsicht: View {
    let modell: WorkoutModell
    let schliessen: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 72))
                .foregroundStyle(.green)
            Text("Workout beendet")
                .font(.title.weight(.bold))
            HStack(spacing: 10) {
                KennzahlKachel(kennzahl: Kennzahl(titel: "Dauer", wert: Zeit.uhr(modell.gesamtdauer), symbol: "clock"))
                KennzahlKachel(kennzahl: Kennzahl(titel: "Sätze", wert: "\(modell.erledigt.count) / \(modell.schritte.count)", symbol: "list.number"))
                KennzahlKachel(kennzahl: Kennzahl(titel: "Wdh.", wert: "\(modell.wiederholungenGesamt)", symbol: "repeat"))
            }
            versandZeile
            Spacer()
            Button(action: schliessen) {
                Text("Fertig")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
        }
        .padding()
    }

    @ViewBuilder private var versandZeile: some View {
        switch modell.versand {
        case .keiner:
            EmptyView()
        case .laeuft:
            HStack(spacing: 10) {
                ProgressView()
                Text("Wird an Garmin übertragen …")
            }
            .karte()
        case .angekommen:
            Label("In Garmin Connect gespeichert. Tri-Coach übernimmt es mit dem nächsten Abgleich.", systemImage: "checkmark.icloud")
                .font(.subheadline)
                .karte()
        case .offen(let grund):
            VStack(alignment: .leading, spacing: 8) {
                Label("Noch nicht in Garmin", systemImage: "icloud.slash")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.orange)
                Text(grund).font(.footnote).foregroundStyle(.secondary)
                Text("Das Training ist auf dem Telefon gespeichert und wird beim nächsten Öffnen der App erneut gesendet.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Button("Jetzt erneut versuchen") { Task { await modell.senden() } }
                    .buttonStyle(.bordered)
            }
            .karte()
        }
    }
}

// MARK: - Zeitangaben

enum Zeit {
    /// 75 → „1:15“, 3725 → „1:02:05“.
    static func uhr(_ sekunden: TimeInterval) -> String {
        let s = max(0, Int(sekunden))
        if s >= 3600 { return String(format: "%d:%02d:%02d", s / 3600, (s % 3600) / 60, s % 60) }
        return String(format: "%d:%02d", s / 60, s % 60)
    }

    /// 45 → „45 s“, 90 → „1:30 min“, 120 → „2 min“.
    static func kurz(_ sekunden: TimeInterval) -> String {
        let s = Int(sekunden)
        if s < 60 { return "\(s) s" }
        if s % 60 == 0 { return "\(s / 60) min" }
        return "\(uhr(sekunden)) min"
    }
}
