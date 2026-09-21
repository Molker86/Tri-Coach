import SwiftUI

struct ErnaehrungView: View {
    @Environment(AppZustand.self) private var app

    var body: some View {
        NavigationStack {
            Group {
                if let plan = app.ernaehrung {
                    PlanListe(plan: plan)
                } else if app.laedt {
                    ProgressView("Lade Ernährungsplan …")
                } else {
                    ContentUnavailableView {
                        Label("Kein Ernährungsplan", systemImage: "fork.knife")
                    } description: {
                        Text(app.fehlermeldung ?? "Erzeuge in Tri-Coach unter „Ernährung“ einen Plan zum aktiven Trainingsblock.")
                    }
                }
            }
            .navigationTitle("Ernährung")
            .refreshable { await app.laden() }
            .navigationDestination(for: ErnaehrungsTag.self) { ErnaehrungsTagView(tag: $0) }
            .navigationDestination(for: PlanEinheit.self) { EinheitDetailView(einheit: $0) }
        }
    }
}

private struct PlanListe: View {
    let plan: Ernaehrungsplan
    @Environment(AppZustand.self) private var app

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Text(Datum.zeitraum(plan.startDate, plan.endDate))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.accentColor)
                        .textCase(.uppercase)
                    Text(plan.title)
                        .font(.headline)
                    if let summary = plan.summary, !summary.isEmpty {
                        Text(summary)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)
                if let begruendung = plan.begruendung, !begruendung.isEmpty {
                    DisclosureGroup("Begründung") {
                        Text(begruendung).font(.subheadline)
                    }
                }
            }

            Section("Tage") {
                ForEach(plan.tage) { tag in
                    NavigationLink(value: tag) {
                        TagZeile(tag: tag, einheiten: app.einheitenAm(tag.tag))
                    }
                }
            }

            if let supplemente = plan.supplemente, !supplemente.isEmpty {
                Section("Supplemente") {
                    ForEach(supplemente.sorted { ($0.orderIndex ?? 0) < ($1.orderIndex ?? 0) }) { eintrag in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack(alignment: .firstTextBaseline) {
                                Text(eintrag.name).font(.subheadline.weight(.semibold))
                                Spacer()
                                if let dosierung = eintrag.dosierung {
                                    Text(dosierung).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            if let zeitpunkt = eintrag.zeitpunkt, !zeitpunkt.isEmpty {
                                Label(zeitpunkt, systemImage: "clock")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            if let begruendung = eintrag.begruendung, !begruendung.isEmpty {
                                Text(begruendung)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }
}

private struct TagZeile: View {
    let tag: ErnaehrungsTag
    let einheiten: [PlanEinheit]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text(Datum.mittel(tag.date))
                    .font(.subheadline.weight(.semibold))
                if Datum.istHeute(tag.date) {
                    Text("Heute")
                        .font(.caption2.weight(.bold))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.accentColor, in: Capsule())
                        .foregroundStyle(.white)
                }
                Spacer()
                ForEach(einheiten.prefix(3)) { einheit in
                    Image(systemName: einheit.sportart.symbol)
                        .font(.caption)
                        .foregroundStyle(einheit.sportart.farbe)
                }
            }
            if let hinweis = tag.trainingshinweis, !hinweis.isEmpty {
                Text(hinweis)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            let makros = [Zahl.ganz(tag.kalorienKcal).map { "\($0) kcal" }, Zahl.makros(kh: tag.kohlenhydrateG, protein: tag.proteinG, fett: tag.fettG)]
                .compactMap { $0 }
                .filter { !$0.isEmpty }
                .joined(separator: " · ")
            if !makros.isEmpty {
                Text(makros)
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }
}

/// Die Ernährung eines Tages als Karte im Kalender.
struct ErnaehrungsTagKarte: View {
    let tag: ErnaehrungsTag

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let hinweis = tag.trainingshinweis, !hinweis.isEmpty {
                Text(hinweis)
                    .font(.subheadline)
                    .foregroundStyle(.primary)
                    .multilineTextAlignment(.leading)
            }
            MakroLeiste(kcal: tag.kalorienKcal, kh: tag.kohlenhydrateG, protein: tag.proteinG, fett: tag.fettG)
            VStack(alignment: .leading, spacing: 6) {
                ForEach(tag.mahlzeitenSortiert) { mahlzeit in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(mahlzeit.name)
                            .font(.subheadline)
                            .foregroundStyle(.primary)
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 8)
                        Text(mahlzeit.zeitpunkt)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.trailing)
                    }
                }
            }
            if !tag.einnahmenSortiert.isEmpty {
                Label(
                    tag.einnahmenSortiert.map(\.name).joined(separator: ", "),
                    systemImage: "pills"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            HStack {
                Text("Tagesplan ansehen")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color.accentColor)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.tertiary)
            }
        }
        .karte()
    }
}
