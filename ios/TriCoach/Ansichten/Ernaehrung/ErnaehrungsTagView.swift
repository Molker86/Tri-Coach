import SwiftUI

struct ErnaehrungsTagView: View {
    let tag: ErnaehrungsTag
    @Environment(AppZustand.self) private var app

    var body: some View {
        List {
            Section {
                if let hinweis = tag.trainingshinweis, !hinweis.isEmpty {
                    Text(hinweis)
                }
                MakroLeiste(kcal: tag.kalorienKcal, kh: tag.kohlenhydrateG, protein: tag.proteinG, fett: tag.fettG)
                    .listRowInsets(EdgeInsets(top: 10, leading: 12, bottom: 10, trailing: 12))
                if let ml = tag.fluessigkeitMl {
                    LabeledContent("Flüssigkeit") {
                        Text(ml >= 1000 ? "\(Zahl.kurz(ml / 1000, stellen: 1) ?? "") l" : "\(Zahl.ganz(ml) ?? "") ml")
                    }
                }
            }

            let einheiten = app.einheitenAm(tag.tag)
            if !einheiten.isEmpty {
                Section("Training an diesem Tag") {
                    ForEach(einheiten) { einheit in
                        NavigationLink(value: einheit) {
                            HStack(spacing: 10) {
                                SportSymbol(sportart: einheit.sportart, groesse: 28)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(einheit.title).font(.subheadline.weight(.semibold))
                                    if let dauer = Zahl.dauer(einheit.durationMin) {
                                        Text(dauer).font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Section("Mahlzeiten") {
                ForEach(tag.mahlzeitenSortiert) { MahlzeitZeile(mahlzeit: $0) }
            }

            if !tag.einnahmenSortiert.isEmpty {
                Section("Supplemente") {
                    ForEach(tag.einnahmenSortiert) { gabe in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(gabe.name).font(.subheadline.weight(.semibold))
                                if let dosierung = gabe.dosierung, !dosierung.isEmpty {
                                    Text(dosierung).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            Spacer(minLength: 8)
                            Text(gabe.zeitpunkt)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.trailing)
                        }
                    }
                }
            }

            if let notiz = tag.notiz, !notiz.isEmpty {
                Section("Notiz") {
                    Text(notiz).font(.subheadline)
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(Datum.mittel(tag.date))
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct MahlzeitZeile: View {
    let mahlzeit: Mahlzeit
    @State private var zeigeZutaten = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(mahlzeit.zeitpunkt)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color.accentColor)
                BezugMarke(bezug: mahlzeit.bezug)
                Spacer()
                if let kcal = Zahl.ganz(mahlzeit.kalorienKcal) {
                    Text("\(kcal) kcal")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            Text(mahlzeit.name)
                .font(.headline)
            if let beschreibung = mahlzeit.beschreibung, !beschreibung.isEmpty {
                Text(beschreibung)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            let makros = Zahl.makros(kh: mahlzeit.kohlenhydrateG, protein: mahlzeit.proteinG, fett: mahlzeit.fettG)
            if !makros.isEmpty {
                Text(makros)
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            if let zutaten = mahlzeit.zutaten, !zutaten.isEmpty {
                DisclosureGroup(isExpanded: $zeigeZutaten) {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(zutaten) { zutat in
                            HStack {
                                Text(zutat.name)
                                Spacer()
                                Text(Zahl.menge(zutat))
                                    .foregroundStyle(.secondary)
                                    .monospacedDigit()
                            }
                            .font(.subheadline)
                        }
                    }
                    .padding(.top, 4)
                } label: {
                    Text("Zutaten (\(zutaten.count))")
                        .font(.subheadline.weight(.semibold))
                }
            }
        }
        .padding(.vertical, 4)
    }
}
