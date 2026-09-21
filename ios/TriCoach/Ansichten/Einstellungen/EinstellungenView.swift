import SwiftUI

struct EinstellungenView: View {
    @Environment(AppZustand.self) private var app
    @State private var zeigeVerbindung = false
    @State private var bestaetigeAbmelden = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Konto") {
                    LabeledContent("Angemeldet als", value: app.konto?.username ?? "–")
                }

                Section("Verbindung") {
                    LabeledContent("Art", value: app.entwurf.art.bezeichnung)
                    LabeledContent("Adresse", value: app.entwurf.angezeigteAdresse)
                    Button("Verbindung ändern …") { zeigeVerbindung = true }
                }

                Section("Daten") {
                    if let zeit = app.zuletztGeladen {
                        LabeledContent("Zuletzt geladen", value: zeit.formatted(date: .abbreviated, time: .shortened))
                    }
                    if let fehler = app.fehlermeldung {
                        Text(fehler)
                            .font(.footnote)
                            .foregroundStyle(Color.red)
                    }
                    Button {
                        Task { await app.laden() }
                    } label: {
                        HStack {
                            Text("Jetzt aktualisieren")
                            Spacer()
                            if app.laedt { ProgressView() }
                        }
                    }
                    .disabled(app.laedt)
                }

                Section {
                    Button("Abmelden", role: .destructive) { bestaetigeAbmelden = true }
                }

                Section {
                    LabeledContent("Version", value: Bundle.main.versionsText)
                }
            }
            .navigationTitle("Einstellungen")
            .sheet(isPresented: $zeigeVerbindung) {
                NavigationStack {
                    EinrichtungView(entwurf: app.entwurf, alsSheet: true)
                        .navigationTitle("Verbindung")
                        .navigationBarTitleDisplayMode(.inline)
                }
            }
            .confirmationDialog("Wirklich abmelden?", isPresented: $bestaetigeAbmelden, titleVisibility: .visible) {
                Button("Abmelden", role: .destructive) { app.abmelden() }
            } message: {
                Text("Die Verbindungsdaten bleiben erhalten, nur die Kontoauswahl wird zurückgesetzt.")
            }
        }
    }
}

/// Verbindung einrichten und Konto wählen — beim ersten Start und aus den Einstellungen.
struct EinrichtungView: View {
    @Environment(AppZustand.self) private var app
    @Environment(\.dismiss) private var dismiss

    @State private var entwurf: VerbindungsEntwurf
    @State private var konten: [Konto] = []
    @State private var gewaehlteKontoID: Int?
    @State private var arbeitet = false
    @State private var fehler: String?
    @State private var zeigeToken = false
    private let alsSheet: Bool

    init(entwurf: VerbindungsEntwurf, alsSheet: Bool = false) {
        _entwurf = State(initialValue: entwurf)
        self.alsSheet = alsSheet
    }

    var body: some View {
        Form {
            if !alsSheet {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Image(systemName: "figure.run.circle.fill")
                            .font(.system(size: 44))
                            .foregroundStyle(Color.accentColor)
                        Text("Trainings- und Ernährungspläne aus deinem Tri-Coach, direkt auf dem iPhone.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 6)
                }
            }

            Section {
                Picker("Verbindung", selection: $entwurf.art) {
                    ForEach(Verbindungsart.allCases) { art in
                        Text(art.bezeichnung).tag(art)
                    }
                }
                .pickerStyle(.segmented)
            } footer: {
                Text(entwurf.art == .homeAssistant
                     ? "Über den Home-Assistant-Ingress – so wie im Browser. Funktioniert im Heimnetz, per WireGuard oder über Nabu Casa."
                     : "Direkt auf den Tri-Coach-Server, z. B. das lokale Backend beim Entwickeln. Ohne Home Assistant gibt es keinen Zugangsschutz.")
            }

            if entwurf.art == .homeAssistant {
                Section {
                    TextField("http://homeassistant.local:8123", text: $entwurf.homeAssistantAdresse)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    HStack {
                        Group {
                            if zeigeToken {
                                TextField("Langzeit-Zugangstoken", text: $entwurf.homeAssistantToken)
                            } else {
                                SecureField("Langzeit-Zugangstoken", text: $entwurf.homeAssistantToken)
                            }
                        }
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        Button {
                            zeigeToken.toggle()
                        } label: {
                            Image(systemName: zeigeToken ? "eye.slash" : "eye")
                        }
                        .buttonStyle(.borderless)
                        .accessibilityLabel(zeigeToken ? "Token verbergen" : "Token anzeigen")
                    }
                    // Ein Token tippt niemand ab — der Knopf fügt ohne Umweg
                    // über das Kontextmenü ein.
                    Button {
                        if let text = UIPasteboard.general.string?.trimmingCharacters(in: .whitespacesAndNewlines),
                           !text.isEmpty {
                            entwurf.homeAssistantToken = text
                        }
                    } label: {
                        Label("Token aus Zwischenablage einfügen", systemImage: "doc.on.clipboard")
                    }
                    TextField("Add-on-Slug (optional)", text: $entwurf.addonSlug)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Home Assistant")
                } footer: {
                    Text("Token anlegen: Home Assistant → Profil → Sicherheit → Langlebige Zugangstoken. Den Add-on-Slug findet die App selbst – nur eintragen, wenn das nicht klappt.")
                }
            } else {
                Section {
                    TextField("http://localhost:8000", text: $entwurf.direktAdresse)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Server")
                }
            }

            Section {
                Button {
                    Task { await verbinden() }
                } label: {
                    HStack {
                        Text(konten.isEmpty ? "Verbinden" : "Erneut verbinden")
                        Spacer()
                        if arbeitet && konten.isEmpty { ProgressView() }
                    }
                }
                .disabled(arbeitet)
            }

            if !konten.isEmpty {
                Section("Konto wählen") {
                    Picker("Konto", selection: $gewaehlteKontoID) {
                        ForEach(konten) { konto in
                            Text(konto.username).tag(Optional(konto.id))
                        }
                    }
                    .pickerStyle(.inline)
                    .labelsHidden()

                    Button {
                        Task { await anmelden() }
                    } label: {
                        HStack {
                            Text("Anmelden").fontWeight(.semibold)
                            Spacer()
                            if arbeitet { ProgressView() }
                        }
                    }
                    .disabled(gewaehlteKontoID == nil || arbeitet)
                }
            }

            if let fehler {
                Section {
                    Label(fehler, systemImage: "exclamationmark.triangle.fill")
                        .font(.subheadline)
                        .foregroundStyle(Color.red)
                }
            }
        }
        .onChange(of: entwurf) {
            // Eine geänderte Verbindung macht die geladene Kontoliste ungültig.
            konten = []
            gewaehlteKontoID = nil
        }
        .toolbar {
            if alsSheet {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
            }
        }
    }

    private func verbinden() async {
        protokolliere("Verbinden getippt: \(entwurf.art.rawValue), \(entwurf.angezeigteAdresse), Token \(entwurf.homeAssistantToken.isEmpty ? "leer" : "vorhanden (\(entwurf.homeAssistantToken.count) Zeichen)")")
        arbeitet = true
        fehler = nil
        defer { arbeitet = false }
        do {
            let geladen = try await app.kontenLaden(fuer: entwurf)
            protokolliere("Konten: \(geladen.map(\.username).joined(separator: ", "))")
            konten = geladen
            if geladen.isEmpty {
                fehler = "In Tri-Coach gibt es noch kein Konto. Lege eins in der Web-Oberfläche an."
            }
            // Vorausgewählt wird nur, was eindeutig ist: das bisherige Konto oder
            // das einzige. Sonst landete man still im alphabetisch ersten Konto.
            gewaehlteKontoID = geladen.first(where: { $0.id == app.konto?.id })?.id
                ?? (geladen.count == 1 ? geladen.first?.id : nil)
        } catch {
            protokolliere("Verbinden fehlgeschlagen: \(error.localizedDescription)")
            konten = []
            fehler = error.localizedDescription
        }
    }

    private func anmelden() async {
        guard let id = gewaehlteKontoID, let konto = konten.first(where: { $0.id == id }) else { return }
        arbeitet = true
        fehler = nil
        defer { arbeitet = false }
        do {
            try await app.anmelden(konto: konto, mit: entwurf)
            if alsSheet { dismiss() }
        } catch {
            fehler = error.localizedDescription
        }
    }
}
