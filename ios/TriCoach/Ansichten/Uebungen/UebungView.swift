import SwiftUI

/// Eine Übung groß: die Animation, was betont ist, woher sie stammt — und bei
/// einer ungeprüften die beiden Knöpfe Freigeben und Verwerfen.
struct UebungView: View {
    let modell: UebungenModell
    let index: Int

    @Environment(\.dismiss) private var dismiss
    @State private var laeuft = true
    @State private var verwerfenOffen = false
    @State private var arbeitet = false
    @State private var fehler: String?

    private var uebung: EinheitUebung? {
        modell.uebungen.indices.contains(index) ? modell.uebungen[index] : nil
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let uebung, let animation = uebung.animation {
                    buehne(animation)
                    kopf(uebung, animation)
                    if let fehler {
                        FehlerBanner(text: fehler)
                    }
                    if animation.istUngeprueft {
                        pruefung(animation)
                    }
                    ablauf(animation)
                    herkunft(animation)
                }
            }
            .padding()
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle(uebung?.animation?.name ?? "Übung")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let animation = uebung?.animation, !animation.istUngeprueft {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("Animation verwerfen …", systemImage: "hand.thumbsdown", role: .destructive) {
                            verwerfenOffen = true
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
        }
        .sheet(isPresented: $verwerfenOffen) {
            if let animation = uebung?.animation {
                VerwerfenBlatt(name: animation.name) { rueckmeldung in
                    try await modell.verwerfen(animation.schluessel, rueckmeldung: rueckmeldung)
                }
            }
        }
        // Verworfen heißt: Hier gibt es nichts mehr zu sehen.
        .onChange(of: uebung?.animation == nil) { _, weg in
            if weg { dismiss() }
        }
    }

    private func buehne(_ animation: UebungsAnimation) -> some View {
        FigurAnimation(bewegung: animation.bewegung, laeuft: laeuft)
            .aspectRatio(4 / 3, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(alignment: .bottomTrailing) {
                Image(systemName: laeuft ? "pause.fill" : "play.fill")
                    .font(.footnote.weight(.bold))
                    .foregroundStyle(.secondary)
                    .padding(8)
                    .background(.thinMaterial, in: Circle())
                    .padding(10)
            }
            .contentShape(Rectangle())
            .onTapGesture { laeuft.toggle() }
            .accessibilityLabel(laeuft ? "Animation anhalten" : "Animation abspielen")
            .accessibilityAddTraits(.isButton)
    }

    private func kopf(_ uebung: EinheitUebung, _ animation: UebungsAnimation) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(uebung.titel)
                .font(.title3.weight(.bold))
            Text(animation.name)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            if !animation.bewegung.betont.isEmpty {
                HStack(spacing: 6) {
                    ForEach(animation.bewegung.betont, id: \.self) { gruppe in
                        Text(Muskelgruppe.name(gruppe))
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(Color.teal.opacity(0.15), in: Capsule())
                            .foregroundStyle(Color.teal)
                    }
                }
            }
        }
    }

    private func pruefung(_ animation: UebungsAnimation) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Noch nicht geprüft", systemImage: "exclamationmark.bubble.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.orange)
            Text("Diese Animation hat Claude beschrieben. Stimmt die Bewegung? Freigeben gilt für alle Konten. Beim Verwerfen erstellt Claude eine neue — deine Anmerkung geht dabei mit.")
                .font(.subheadline)
            if let hinweise = animation.hinweise, !hinweise.isEmpty {
                Text(hinweise.joined(separator: "\n"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 10) {
                Button {
                    Task { await freigeben(animation) }
                } label: {
                    Label("Freigeben", systemImage: "checkmark.circle.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)

                Button(role: .destructive) {
                    verwerfenOffen = true
                } label: {
                    Label("Verwerfen …", systemImage: "xmark.circle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }
            .disabled(arbeitet)
        }
        .karte()
    }

    private func ablauf(_ animation: UebungsAnimation) -> some View {
        let bilder = animation.bewegung.ablauf
        let dauer = animation.bewegung.dauer
        return VStack(alignment: .leading, spacing: 10) {
            Label("Ablauf", systemImage: "film.stack")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(bilder.indices, id: \.self) { i in
                        VStack(spacing: 4) {
                            FigurStandbild(bewegung: animation.bewegung, bild: i)
                                .frame(width: 104, height: 78)
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            Text(haltezeit(bilder[i].haltenS, nummer: i + 1))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            Text("Eine Schleife dauert \(Zahl.kurz(dauer) ?? "–") s.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .karte()
    }

    private func haltezeit(_ sekunden: Double, nummer: Int) -> String {
        sekunden >= 1 ? "\(nummer) · \(Zahl.kurz(sekunden) ?? "") s halten" : "\(nummer)"
    }

    private func herkunft(_ animation: UebungsAnimation) -> some View {
        let text: String
        if animation.vonKI {
            let modell = animation.modelUsed.map { " (\($0))" } ?? ""
            text = animation.istUngeprueft
                ? "Von Claude erstellt\(modell)."
                : "Von Claude erstellt\(modell) und freigegeben."
        } else {
            text = "Aus der geprüften Tri-Coach-Bibliothek."
        }
        return Label(text, systemImage: animation.vonKI ? "sparkles" : "books.vertical")
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    private func freigeben(_ animation: UebungsAnimation) async {
        arbeitet = true
        defer { arbeitet = false }
        do {
            try await modell.freigeben(animation.schluessel)
            fehler = nil
        } catch {
            fehler = error.localizedDescription
        }
    }
}

/// Fragt, was nicht stimmt — das geht wörtlich in den nächsten Versuch.
private struct VerwerfenBlatt: View {
    let name: String
    let verwerfen: (String) async throws -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var rueckmeldung = ""
    @State private var arbeitet = false
    @State private var fehler: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("z. B. „Das Becken muss höher“", text: $rueckmeldung, axis: .vertical)
                        .lineLimit(3...6)
                } header: {
                    Text("Was stimmt nicht?")
                } footer: {
                    Text("Optional. Claude erstellt beim nächsten Lauf eine neue Animation und bekommt deine Anmerkung dazu.")
                }
                if let fehler {
                    Section { Text(fehler).foregroundStyle(.red) }
                }
            }
            .navigationTitle(name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Verwerfen", role: .destructive) {
                        Task { await bestaetigen() }
                    }
                    .disabled(arbeitet)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func bestaetigen() async {
        arbeitet = true
        defer { arbeitet = false }
        do {
            try await verwerfen(rueckmeldung.trimmingCharacters(in: .whitespacesAndNewlines))
            dismiss()
        } catch {
            fehler = error.localizedDescription
        }
    }
}
