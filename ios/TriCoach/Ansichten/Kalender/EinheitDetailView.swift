import SwiftUI

struct EinheitDetailView: View {
    let einheit: PlanEinheit

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 14) {
                    SportSymbol(sportart: einheit.sportart, groesse: 56)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(einheit.title)
                            .font(.title3.weight(.bold))
                        Text(unterzeile)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Text(Datum.lang(einheit.date))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }

                if einheit.erledigt {
                    Label("Absolviert", systemImage: "checkmark.circle.fill")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.green)
                }

                if !kennzahlen.isEmpty {
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                        ForEach(kennzahlen, id: \.self) { KennzahlKachel(kennzahl: $0) }
                    }
                }

                TextAbschnitt(titel: "Aufbau", text: einheit.structure, symbol: "list.bullet.rectangle")
                TextAbschnitt(titel: "Beschreibung", text: einheit.description, symbol: "text.alignleft")
                TextAbschnitt(titel: "Zweck", text: einheit.purpose, symbol: "target")

                if einheit.angepasstAm != nil {
                    anpassung
                }
            }
            .padding()
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle(einheit.sportart.name)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var unterzeile: String {
        [einheit.sportart.name, Einheitentyp.name(einheit.sessionType)]
            .compactMap { $0 }
            .joined(separator: " · ")
    }

    private var anpassung: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(
                "Angepasst" + (einheit.angepasstAm.map { " am " + Datum.zeitstempel($0) } ?? ""),
                systemImage: "wand.and.stars"
            )
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(Color.orange)
            if let wunsch = einheit.anpassungswunsch, !wunsch.isEmpty {
                Text("„\(wunsch)“").italic()
            }
            if let grund = einheit.anpassungsbegruendung, !grund.isEmpty {
                Text(grund)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .karte()
    }

    private var kennzahlen: [Kennzahl] {
        var liste: [Kennzahl] = []
        if let text = Zahl.dauer(einheit.durationMin) {
            liste.append(Kennzahl(titel: "Dauer", wert: text, symbol: "clock"))
        }
        if let text = Zahl.distanz(einheit.distanceKm) {
            liste.append(Kennzahl(titel: "Distanz", wert: text, symbol: "point.topleft.down.to.point.bottomright.curvepath"))
        }
        if let zone = einheit.intensityZone, !zone.isEmpty {
            liste.append(Kennzahl(titel: "Zone", wert: zone, symbol: "gauge.with.dots.needle.50percent"))
        }
        if let oben = einheit.targetHrHigh {
            let text = einheit.targetHrLow.map { "\(Int($0))–\(Int(oben)) bpm" } ?? "bis \(Int(oben)) bpm"
            liste.append(Kennzahl(titel: "Puls", wert: text, symbol: "heart"))
        }
        if let pace = einheit.targetPace, !pace.isEmpty {
            liste.append(Kennzahl(titel: "Pace", wert: pace, symbol: "speedometer"))
        }
        if let leistung = einheit.targetPower, !leistung.isEmpty {
            liste.append(Kennzahl(titel: "Leistung", wert: leistung, symbol: "bolt"))
        }
        if let rpe = Zahl.kurz(einheit.rpeTarget) {
            liste.append(Kennzahl(titel: "RPE", wert: rpe, symbol: "flame"))
        }
        if let ort = einheit.swimLocation {
            liste.append(Kennzahl(titel: "Ort", wert: ort == "open_water" ? "Freiwasser" : "Becken", symbol: "water.waves"))
        }
        if let ort = einheit.bikeLocation {
            liste.append(Kennzahl(titel: "Ort", wert: ort == "indoor" ? "Rolle" : "Draußen", symbol: "bicycle"))
        }
        return liste
    }
}
