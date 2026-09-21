import SwiftUI

struct KalenderView: View {
    @Environment(AppZustand.self) private var app
    @State private var monat = Datum.monatsanfang(Date())
    @State private var ausgewaehlt = Datum.kalender.startOfDay(for: Date())

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let fehler = app.fehlermeldung {
                        FehlerBanner(text: fehler)
                    }
                    if let plan = app.plan {
                        PlanKopf(plan: plan)
                    } else if !app.laedt, app.fehlermeldung == nil {
                        HinweisKarte(
                            symbol: "calendar.badge.exclamationmark",
                            titel: "Kein aktiver Trainingsblock",
                            text: "Sobald in Tri-Coach ein Block übernommen ist, erscheint er hier."
                        )
                    }
                    MonatsKalender(monat: $monat, ausgewaehlt: $ausgewaehlt)
                    TagesUebersicht(datum: ausgewaehlt)
                }
                .padding()
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Kalender")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Heute", action: springeZuHeute)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if app.laedt {
                        ProgressView()
                    } else if let konto = app.konto {
                        Label(konto.username, systemImage: "person.crop.circle")
                            .labelStyle(.titleAndIcon)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .refreshable { await app.laden() }
            .navigationDestination(for: PlanEinheit.self) { EinheitDetailView(einheit: $0) }
            .navigationDestination(for: ErnaehrungsTag.self) { ErnaehrungsTagView(tag: $0) }
        }
    }

    private func springeZuHeute() {
        let heute = Datum.kalender.startOfDay(for: Date())
        withAnimation(.snappy) {
            ausgewaehlt = heute
            monat = Datum.monatsanfang(heute)
        }
    }
}

private struct PlanKopf: View {
    let plan: TrainingsPlan

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Aktiver Block · \(Datum.zeitraum(plan.startDate, plan.endDate))")
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.accentColor)
                .textCase(.uppercase)
            Text(plan.title)
                .font(.headline)
            if let summary = plan.summary, !summary.isEmpty {
                Text(summary)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
            }
            if let notizen = plan.coachingNotes, !notizen.isEmpty {
                DisclosureGroup("Coaching-Hinweise") {
                    Text(notizen)
                        .font(.subheadline)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.top, 4)
                }
                .font(.subheadline.weight(.semibold))
            }
        }
        .karte()
    }
}

// MARK: - Monatsblatt

struct MonatsKalender: View {
    @Binding var monat: Date
    @Binding var ausgewaehlt: Date
    @Environment(AppZustand.self) private var app

    private let spalten = Array(repeating: GridItem(.flexible(), spacing: 2), count: 7)

    var body: some View {
        VStack(spacing: 8) {
            HStack {
                Button { blaettern(-1) } label: {
                    Image(systemName: "chevron.left").frame(width: 36, height: 36)
                }
                .accessibilityLabel("Vorheriger Monat")
                Spacer()
                Text(Datum.monatstitel(monat))
                    .font(.headline)
                Spacer()
                Button { blaettern(1) } label: {
                    Image(systemName: "chevron.right").frame(width: 36, height: 36)
                }
                .accessibilityLabel("Nächster Monat")
            }

            LazyVGrid(columns: spalten, spacing: 2) {
                ForEach(Datum.wochentagsKuerzel, id: \.self) { kuerzel in
                    Text(kuerzel)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                ForEach(Array(Datum.zellen(fuer: monat).enumerated()), id: \.offset) { _, tag in
                    if let tag {
                        let schluessel = Datum.schluessel(tag)
                        TagesZelle(
                            datum: tag,
                            istAusgewaehlt: Datum.kalender.isDate(tag, inSameDayAs: ausgewaehlt),
                            einheiten: app.einheitenAm(schluessel),
                            absolviert: !app.absolviertAm(schluessel).isEmpty,
                            hatErnaehrung: app.ernaehrungAm(schluessel) != nil
                        )
                        .onTapGesture { ausgewaehlt = tag }
                    } else {
                        Color.clear.frame(height: 50)
                    }
                }
            }
        }
        .karte()
        .simultaneousGesture(
            DragGesture(minimumDistance: 30).onEnded { geste in
                guard abs(geste.translation.width) > abs(geste.translation.height) * 1.5 else { return }
                blaettern(geste.translation.width < 0 ? 1 : -1)
            }
        )
    }

    private func blaettern(_ schritt: Int) {
        guard let neu = Datum.kalender.date(byAdding: .month, value: schritt, to: monat) else { return }
        withAnimation(.snappy) { monat = neu }
    }
}

private struct TagesZelle: View {
    let datum: Date
    let istAusgewaehlt: Bool
    let einheiten: [PlanEinheit]
    let absolviert: Bool
    let hatErnaehrung: Bool

    private var istHeute: Bool { Datum.kalender.isDateInToday(datum) }

    var body: some View {
        VStack(spacing: 3) {
            Text("\(Datum.kalender.component(.day, from: datum))")
                .font(.callout.weight(istHeute || istAusgewaehlt ? .bold : .regular).monospacedDigit())
                .foregroundStyle(zifferFarbe)
                .frame(width: 32, height: 32)
                .background {
                    if istAusgewaehlt {
                        Circle().fill(Color.accentColor)
                    } else if istHeute {
                        Circle().strokeBorder(Color.accentColor, lineWidth: 1.5)
                    }
                }
            HStack(spacing: 3) {
                ForEach(einheiten.prefix(3)) { einheit in
                    Circle()
                        .fill(einheit.sportart.farbe.opacity(einheit.sportart == .rest ? 0.4 : 1))
                        .frame(width: 6, height: 6)
                }
                if einheiten.isEmpty && absolviert {
                    Image(systemName: "checkmark")
                        .font(.system(size: 7, weight: .heavy))
                        .foregroundStyle(Color.green)
                }
            }
            .frame(height: 7)
            Capsule()
                .fill(hatErnaehrung ? Color.accentColor.opacity(0.45) : Color.clear)
                .frame(width: 14, height: 2)
        }
        .frame(maxWidth: .infinity, minHeight: 50)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(barrierefreiText)
        .accessibilityAddTraits(istAusgewaehlt ? [.isButton, .isSelected] : .isButton)
    }

    private var zifferFarbe: Color {
        if istAusgewaehlt { return .white }
        if istHeute { return .accentColor }
        return .primary
    }

    private var barrierefreiText: String {
        var teile = [Datum.lang(datum)]
        if !einheiten.isEmpty {
            teile.append(einheiten.map(\.sportart.name).joined(separator: ", "))
        }
        if absolviert { teile.append("absolviert") }
        return teile.joined(separator: ", ")
    }
}

// MARK: - Der ausgewählte Tag

struct TagesUebersicht: View {
    let datum: Date
    @Environment(AppZustand.self) private var app

    var body: some View {
        let schluessel = Datum.schluessel(datum)
        let einheiten = app.einheitenAm(schluessel)
        let erledigt = app.absolviertAm(schluessel)
        let essen = app.ernaehrungAm(schluessel)

        VStack(alignment: .leading, spacing: 10) {
            Text(Datum.lang(datum))
                .font(.title3.weight(.semibold))
                .padding(.top, 4)

            AbschnittTitel("Training", symbol: "figure.run")
            if einheiten.isEmpty {
                Text(app.plan == nil ? "Kein Trainingsblock geladen." : "Für diesen Tag ist nichts geplant.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .karte()
            } else {
                ForEach(einheiten) { einheit in
                    NavigationLink(value: einheit) {
                        EinheitKarte(einheit: einheit)
                    }
                    .buttonStyle(.plain)
                }
            }

            if !erledigt.isEmpty {
                AbschnittTitel("Absolviert", symbol: "checkmark.circle")
                ForEach(erledigt) { AbsolviertKarte(einheit: $0) }
            }

            AbschnittTitel("Ernährung", symbol: "fork.knife")
            if let essen {
                NavigationLink(value: essen) {
                    ErnaehrungsTagKarte(tag: essen)
                }
                .buttonStyle(.plain)
            } else {
                Text(app.ernaehrung == nil ? "Kein Ernährungsplan vorhanden." : "Der Ernährungsplan deckt diesen Tag nicht ab.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .karte()
            }
        }
    }
}

struct EinheitKarte: View {
    let einheit: PlanEinheit

    var body: some View {
        HStack(spacing: 12) {
            SportSymbol(sportart: einheit.sportart)
            VStack(alignment: .leading, spacing: 3) {
                Text(einheit.title)
                    .font(.headline)
                    .foregroundStyle(.primary)
                    .multilineTextAlignment(.leading)
                Text(untertitel)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if einheit.angepasstAm != nil {
                    Label("angepasst", systemImage: "wand.and.stars")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.orange)
                }
            }
            Spacer(minLength: 0)
            if einheit.erledigt {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(Color.green)
                    .accessibilityLabel("erledigt")
            }
            Image(systemName: "chevron.right")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .karte()
    }

    private var untertitel: String {
        let teile = [
            Einheitentyp.name(einheit.sessionType),
            Zahl.dauer(einheit.durationMin),
            Zahl.distanz(einheit.distanceKm),
            einheit.intensityZone,
        ]
        let text = teile.compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
        return text.isEmpty ? einheit.sportart.name : text
    }
}

struct AbsolviertKarte: View {
    let einheit: AbsolvierteEinheit

    var body: some View {
        HStack(spacing: 12) {
            SportSymbol(sportart: einheit.sportart, groesse: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text(einheit.sportart.name)
                    .font(.subheadline.weight(.semibold))
                if !werte.isEmpty {
                    Text(werte)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
            if einheit.status == "skipped" {
                Image(systemName: "xmark.circle").foregroundStyle(Color.red)
            } else {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(Color.green)
            }
        }
        .karte()
    }

    private var werte: String {
        [
            Zahl.dauer(einheit.durationMin),
            Zahl.distanz(einheit.distanceKm),
            einheit.avgHr.map { "Ø \(Int($0.rounded())) bpm" },
            Zahl.pace(einheit.avgPace, einheit.sportart),
            einheit.avgPower.map { "Ø \(Int($0.rounded())) W" },
        ]
        .compactMap { $0 }
        .joined(separator: " · ")
    }
}
