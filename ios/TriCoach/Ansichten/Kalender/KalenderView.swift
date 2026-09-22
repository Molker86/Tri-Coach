import SwiftUI

struct KalenderView: View {
    @Environment(AppZustand.self) private var app
    @State private var monat = Datum.monatsanfang(Date())
    @State private var ausgewaehlt = Datum.kalender.startOfDay(for: Date())
    @State private var pfad = NavigationPath()
    /// Wird bei „Heute“ hochgezählt — der Anlass, nach oben zu rollen, auch
    /// wenn heute schon ausgewählt war.
    @State private var zurueckNachOben = 0

    private enum Anker: Hashable { case heute, auswahl }

    var body: some View {
        // Bei jedem Zeichnen neu bestimmt, nicht einmal beim Start: Bleibt die
        // App über Mitternacht offen, rückt „Heute“ mit dem nächsten Neuladen
        // (Rückkehr in die App, Herunterziehen) auf den neuen Tag.
        let heute = Datum.kalender.startOfDay(for: Date())

        NavigationStack(path: $pfad) {
            ScrollViewReader { leser in
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        if let fehler = app.fehlermeldung {
                            FehlerBanner(text: fehler)
                        }

                        // Der heutige Tag steht immer oben — dafür öffnet man
                        // die App. Den Block als Ganzes zeigt der Kalender darunter.
                        TagesUebersicht(datum: heute, ueberschrift: "Heute")
                            .id(Anker.heute)

                        MonatsKalender(monat: $monat, ausgewaehlt: $ausgewaehlt)

                        // Ein anderer Tag erscheint unter dem Kalender; heute
                        // steht schon oben und käme sonst doppelt.
                        if !Datum.kalender.isDate(ausgewaehlt, inSameDayAs: heute) {
                            TagesUebersicht(datum: ausgewaehlt)
                                .id(Anker.auswahl)
                        }
                    }
                    .padding()
                }
                .onChange(of: ausgewaehlt) { _, tag in
                    let istHeute = Datum.kalender.isDate(tag, inSameDayAs: heute)
                    withAnimation(.snappy) {
                        leser.scrollTo(istHeute ? Anker.heute : Anker.auswahl, anchor: .top)
                    }
                }
                .onChange(of: zurueckNachOben) { _, _ in
                    withAnimation(.snappy) { leser.scrollTo(Anker.heute, anchor: .top) }
                }
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
        #if DEBUG && targetEnvironment(simulator)
        .task(id: app.plan?.id) { oeffneFuerEntwicklung() }
        #endif
    }

    #if DEBUG && targetEnvironment(simulator)
    /// `start_einheit` in `ios/Lokal/zugang.json` öffnet eine Einheit von selbst:
    /// eine Kennung oder eine Sportart („strength“ = die nächste Krafteinheit ab
    /// heute). Einmal je Start — im Simulator kommen Klicks nicht immer an.
    private func oeffneFuerEntwicklung() {
        guard !Entwicklungsstart.einheitGeoeffnet,
              let ziel = Entwicklungszugang.laden()?.startEinheit,
              let plan = app.plan
        else { return }
        let heute = Datum.schluessel(Date())
        let sortiert = plan.sessions.sorted { ($0.tag, $0.orderInDay ?? 0) < ($1.tag, $1.orderInDay ?? 0) }
        let treffer = Int(ziel).flatMap { id in sortiert.first { $0.id == id } }
            ?? sortiert.first { $0.sport == ziel && $0.tag >= heute }
            ?? sortiert.first { $0.sport == ziel }
        guard let treffer else {
            protokolliere("start_einheit „\(ziel)“: keine passende Einheit im Plan")
            return
        }
        Entwicklungsstart.einheitGeoeffnet = true
        protokolliere("Öffne Einheit \(treffer.id) (\(treffer.sport), \(treffer.tag)) für die Entwicklung")
        pfad.append(treffer)
    }
    #endif

    private func springeZuHeute() {
        let heute = Datum.kalender.startOfDay(for: Date())
        withAnimation(.snappy) {
            ausgewaehlt = heute
            monat = Datum.monatsanfang(heute)
        }
        zurueckNachOben += 1
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
    /// „Heute“ über dem Datum — für den Tag oben auf der Seite.
    var ueberschrift: String? = nil
    @Environment(AppZustand.self) private var app

    var body: some View {
        let schluessel = Datum.schluessel(datum)
        let einheiten = app.einheitenAm(schluessel)
        let erledigt = app.absolviertAm(schluessel)
        let essen = app.ernaehrungAm(schluessel)

        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                if let ueberschrift {
                    Text(ueberschrift)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.accentColor)
                        .textCase(.uppercase)
                }
                Text(Datum.lang(datum))
                    .font(ueberschrift == nil ? .title3.weight(.semibold) : .title2.weight(.bold))
            }
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
